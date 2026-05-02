"""
core/quota.py — Reusable quota enforcement dependency for plugins.

修复说明（竞态条件）
─────────────────────────────────────────────────────────────────────────────
问题根因：
  1. SQLite + aiosqlite 不支持 SELECT FOR UPDATE。
     该语句会被静默忽略——不报错、不加锁，并发写入毫无保护。

  2. SQLAlchemy Session 内置 identity map（一级缓存）。
     同一个 Session 内，对同一 user_id 执行第二次 SELECT，
     SQLAlchemy 直接返回内存中已缓存的旧对象，根本不查数据库。
     因此 scheduler 在 04:01 写入归零结果后，
     require_quota 在同一 Session 里仍然读到归零前的 used 值，
     再 +1 后提交，就把归零覆盖掉了。

修复方案：
  - 用 asyncio.Lock（每用户一把，存储在 database.py）替代无效的 FOR UPDATE。
  - 拿锁后调用 db.expire_all()，强制使当前 Session 的 identity map 失效，
    下一次访问 ORM 属性时必须重新查数据库，保证读到最新值。
  - scheduler.py 的 reset_all_quotas 也改用同一把锁，
    从而与 require_quota 互斥，彻底消除竞态窗口。
─────────────────────────────────────────────────────────────────────────────
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

# RPM 内存记录：{ user_id: { plugin_name: [timestamp, ...] } }
# RPM 本身是内存级限速，精度够用；总量配额走数据库 + 应用层锁。
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

        # ── 1. RPM 速率限制（内存，加锁）───────────────────────────────────
        if rpm_limit is not None:
            async with _rpm_lock:
                now = time.time()
                history = [
                    ts for ts in _rpm_records[user.id][plugin_name]
                    if now - ts < 60.0
                ]
                if len(history) >= rpm_limit:
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

        # ── 2 & 3 & 4 & 5. 配额检查 + 原子递增（应用层锁）──────────────────
        #
        # 修复要点：
        #
        # ① 用 get_user_quota_lock(user.id) 拿到该用户的 asyncio.Lock。
        #   此锁与 scheduler.reset_all_quotas 共用，保证两处写操作互斥。
        #
        # ② 拿锁后立即调用 db.expire_all()。
        #   原因：SQLAlchemy Session 维护 identity map（一级缓存）。
        #   同一 Session 内，若 user 对象已被缓存，再次 SELECT 不会查库，
        #   直接返回内存中的旧对象——scheduler 刚写入的归零结果就这样被跳过了。
        #   expire_all() 使缓存失效，下次访问任何 ORM 属性时强制重查数据库。
        #
        # ③ 重新 SELECT User（不加 with_for_update，SQLite 上该语句无效）。
        #   拿到的是数据库当前最新值。
        #
        # ④ 读-判-改-commit 全程在锁内完成，与其他协程串行化。
        #
        quota_lock = await get_user_quota_lock(user.id)
        async with quota_lock:
            # 强制使 Session identity map 失效，下一次 SELECT 必须查库
            db.expire_all()

            result = await db.execute(
                select(User).where(User.id == user.id)
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