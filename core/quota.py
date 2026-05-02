"""
core/quota.py — Reusable quota enforcement dependency for plugins.
"""
import importlib, os, hashlib
import time
import asyncio
from collections import defaultdict
from datetime import datetime
from fastapi import Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from core.database import get_db, User, ApiKey, RequestLog
from core.auth_utils import decode_token

PLUGINS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "plugins")

_bearer = HTTPBearer(auto_error=False)

# RPM 内存记录：{ user_id: { plugin_name: [timestamp, ...] } }
# 注意：RPM 本身是内存级限速，精度够用；总量配额必须走数据库行锁。
_rpm_records: dict[int, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
# 保护 _rpm_records 的异步锁，防止协程并发写同一列表
_rpm_lock = asyncio.Lock()


def cleanup_rpm_records():
    """定期清理过期的 RPM 记录，防止内存无限增长。由 scheduler 每 10 分钟调用一次。"""
    now = time.time()
    empty_users = []
    for user_id, plugins_history in _rpm_records.items():
        empty_plugins = []
        for plugin, history in plugins_history.items():
            valid = [ts for ts in history if now - ts < 60]
            if valid:
                plugins_history[plugin] = valid
            else:
                empty_plugins.append(plugin)
        for plugin in empty_plugins:
            del plugins_history[plugin]
        if not plugins_history:
            empty_users.append(user_id)
    for user_id in empty_users:
        del _rpm_records[user_id]


def _hash_key(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer),
    db: AsyncSession = Depends(get_db),
) -> User:
    if credentials is None:
        raise HTTPException(status_code=401, detail="Not authenticated")

    token = credentials.credentials

    # ── Path 1: API Key (starts with "sk-") ──────────────────────────────────
    if token.startswith("sk-"):
        key_hash = _hash_key(token)
        result = await db.execute(
            select(ApiKey).where(ApiKey.key_hash == key_hash, ApiKey.is_active == True)
        )
        api_key = result.scalar_one_or_none()
        if not api_key:
            raise HTTPException(status_code=401, detail="Invalid or revoked API key")

        try:
            api_key.last_used_at = datetime.utcnow()
            await db.commit()
        except Exception:
            pass

        user_result = await db.execute(select(User).where(User.id == api_key.user_id))
        user = user_result.scalar_one_or_none()
        if not user:
            raise HTTPException(status_code=401, detail="User not found")
        return user

    # ── Path 2: JWT Bearer token ──────────────────────────────────────────────
    payload = decode_token(token)
    user_id = int(payload.get("sub", 0))
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return user


async def get_current_admin(user: User = Depends(get_current_user)) -> User:
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    return user


def require_quota(plugin_name: str):
    """
    返回一个 FastAPI dependency，完成以下工作：

    1. RPM 速率限制检查（内存级，异步锁保护）。
    2. 用同一个 Session 重新加载 User 行并加行锁（SELECT ... FOR UPDATE），
       保证并发请求不会读到同一份旧的 used 值。
    3. 检查总量配额是否耗尽。
    4. 原子递增 used 并提交。

    关键修复：
    - require_quota 内部不再依赖 get_current_user 传入的 user 对象（那个对象
      属于另一个 Session，在本 Session 里提交对它的修改是无效的）。
    - 改为用 user.id 在本 Session 内用 with_for_update() 重新查询，确保
      读-改-写在同一个事务和同一个 Session 内完成。
    """
    async def _check(
        # 只从 get_current_user 取 user.id，不直接操作该对象
        user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
    ):
        # ── 加载插件配置 ────────────────────────────────────────────────────
        try:
            cfg = importlib.import_module(f"plugins.{plugin_name}.config")
            default_limit = getattr(cfg, "QUOTA_DEFAULT", None)
            rpm_limit = getattr(cfg, "RPM", None)
        except Exception:
            default_limit = None
            rpm_limit = None

        # ── 1. RPM 速率限制（内存，加锁）───────────────────────────────────
        if rpm_limit is not None:
            async with _rpm_lock:
                now = time.time()
                history = [
                    ts for ts in _rpm_records[user.id][plugin_name]
                    if now - ts < 60.0
                ]
                if len(history) >= rpm_limit:
                    # 顺手写回清理后的列表
                    _rpm_records[user.id][plugin_name] = history
                    raise HTTPException(
                        status_code=429,
                        detail=(
                            f"Rate limit exceeded for {plugin_name}. "
                            f"Max {rpm_limit} requests per minute."
                        ),
                    )
                history.append(now)
                _rpm_records[user.id][plugin_name] = history

        # ── 2 & 3 & 4. 配额检查 + 原子递增（数据库行锁）─────────────────────
        #
        # 必须在 *本 Session (db)* 内重新加载 user 行，并加 FOR UPDATE 行锁。
        # 原因：
        #   - get_current_user 使用的是另一个 Session 实例（FastAPI Depends
        #     每次都会创建新 Session），直接在那个对象上修改再用本 db commit
        #     是无效的——本 Session 根本没有追踪那个对象。
        #   - with_for_update() 确保同一用户的并发请求串行化，避免
        #     "同时读到 used=5，同时写入 used=6" 的丢失更新问题。
        #
        result = await db.execute(
            select(User)
            .where(User.id == user.id)
            .with_for_update()          # 行锁：同一行的其他写事务必须等待
        )
        locked_user = result.scalar_one_or_none()
        if not locked_user:
            raise HTTPException(status_code=401, detail="User not found")

        quota = locked_user.quota  # 通过 @property 解析 JSON，得到最新数据

        # 懒初始化：首次使用该插件时写入默认配额
        if plugin_name not in quota:
            quota[plugin_name] = {"used": 0, "limit": default_limit}

        entry = quota[plugin_name]
        limit = entry.get("limit")
        used = entry.get("used", 0)

        if limit is not None and used >= limit:
            raise HTTPException(
                status_code=429,
                detail=f"Quota exceeded for {plugin_name}. Used: {used}/{limit}",
            )

        # 递增并持久化
        entry["used"] = used + 1
        quota[plugin_name] = entry
        locked_user.quota = quota   # 触发 @quota.setter → 更新 quota_json
        await db.commit()

    return _check


async def log_request(
    db: AsyncSession,
    user: User,
    plugin: str,
    endpoint: str,
    status_code: int,
    extra: dict = None,
):
    import json
    log = RequestLog(
        user_id=user.id,
        plugin=plugin,
        endpoint=endpoint,
        status_code=status_code,
        extra_json=json.dumps(extra or {}),
    )
    db.add(log)
    await db.commit()