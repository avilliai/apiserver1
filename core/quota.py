"""
core/quota.py — Reusable quota enforcement dependency for plugins.
"""
import importlib
import os
import hashlib
import time
import asyncio
from collections import defaultdict
from datetime import datetime
from fastapi import Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from core.database import get_db, User, ApiKey, RequestLog, get_user_quota_lock
from core.auth_utils import decode_token

PLUGINS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "plugins")

_bearer = HTTPBearer(auto_error=False)

_rpm_records: dict[int, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
_rpm_lock = asyncio.Lock()


async def cleanup_rpm_records():
    """
    定期清理过期的 RPM 记录，防止内存无限增长。由 scheduler 每 10 分钟调用一次。
    注意：必须是 async def 并在锁的保护下执行，否则 APScheduler 的后台线程会与主协程产生严重的竞态条件！
    """
    async with _rpm_lock:
        now = time.time()
        empty_users =[]
        for user_id, plugins_history in _rpm_records.items():
            empty_plugins =[]
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

    1. RPM 速率限制检查（内存级，asyncio.Lock 保护）。
    2. 获取该用户的应用层 quota 写锁（database.get_user_quota_lock）。
    3. 拿锁后调用 db.expire_all()，强制使 Session identity map 失效，
       保证下一步 SELECT 必须重新查数据库（读到 scheduler 可能刚写入的归零值）。
    4. 重新 SELECT User 行，检查总量配额是否耗尽。
    5. 原子递增 used 并提交。

    关键设计：
    - require_quota 与 scheduler.reset_all_quotas 共用同一把 per-user asyncio.Lock，
      因此两者天然互斥——scheduler 持锁归零时，require_quota 必须等待；
      require_quota 持锁递增时，scheduler 也必须等待。
    - 不再依赖 SELECT FOR UPDATE（SQLite + aiosqlite 会静默忽略该语句）。
    - 不再依赖 get_current_user 传入的 user 对象直接写库（跨 Session 无效）。
    """
    async def _check(
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

        # 必须在 expire_all() 之前把 user.id 取出为普通 int。
        # expire_all() 会将 user 对象标记为 expired；之后若再访问 user.id，
        # SQLAlchemy 会尝试同步懒加载，在 asyncio 上下文中触发
        # MissingGreenlet 崩溃。取出后，此函数内不再访问 user 对象的任何属性。
        user_id: int = user.id

        # ── 1. RPM 速率限制（内存，加锁）───────────────────────────────────
        if rpm_limit is not None:
            async with _rpm_lock:
                now = time.time()
                history = [
                    ts for ts in _rpm_records[user_id][plugin_name]
                    if now - ts < 60.0
                ]
                if len(history) >= rpm_limit:
                    _rpm_records[user_id][plugin_name] = history
                    raise HTTPException(
                        status_code=429,
                        detail=(
                            f"Rate limit exceeded for {plugin_name}. "
                            f"Max {rpm_limit} requests per minute."
                        ),
                    )
                history.append(now)
                _rpm_records[user_id][plugin_name] = history

        quota_lock = await get_user_quota_lock(user_id)
        async with quota_lock:
            # 强制使 Session identity map 失效，下一次 SELECT 必须查库
            db.expire_all()

            result = await db.execute(
                select(User).where(User.id == user_id)
            )
            locked_user = result.scalar_one_or_none()
            if not locked_user:
                raise HTTPException(status_code=401, detail="User not found")

            quota = locked_user.quota  # @property：每次调用都解析 JSON，返回新 dict

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
            locked_user.quota = quota  # @quota.setter：更新 quota_json
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