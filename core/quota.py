"""
core/quota.py — Reusable quota enforcement dependency for plugins.
"""
import importlib, pkgutil, os, hashlib
import time
from collections import defaultdict
from datetime import datetime
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm.attributes import flag_modified  # ← 新增，确保 JSON 字段变更被追踪

from core.database import get_db, User, ApiKey, RequestLog
from core.auth_utils import decode_token

PLUGINS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "plugins")

_bearer = HTTPBearer(auto_error=False)

# 用于记录每个用户调用各个插件的时间戳，以实现 RPM 速率限制
# 结构: { user_id: { plugin_name: [timestamp1, timestamp2, ...] } }
_rpm_records: dict[int, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))


def cleanup_rpm_records():
    """定期清理过期的速率限制记录，防止内存泄露"""
    now = time.time()
    empty_users = []
    for user_id, plugins_history in _rpm_records.items():
        empty_plugins = []
        for plugin, history in plugins_history.items():
            # 只保留过去 60 秒内的记录
            valid_history = [ts for ts in history if now - ts < 60]
            if valid_history:
                plugins_history[plugin] = valid_history
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
    Returns a FastAPI dependency that:
    1. Checks if RPM rate limit is exceeded (None = unmetered RPM).
    2. Re-fetches the user row with SELECT FOR UPDATE to serialize concurrent writes.
    3. Lazy-inits the user's quota entry for `plugin_name`.
    4. Checks if global quota limit is reached (None = unlimited total).
    5. Increments used count atomically within the lock.

    修复说明：
    - 原实现直接使用 get_current_user 返回的 user 对象读写 quota，
      与 reset_all_quotas（以及其他并发请求）之间存在读-改-写竞态：
        CRON reset:  READ(used=5) → set used=0 → WRITE
        并发请求:               READ(used=5) →            used+1=6 → WRITE  ← 覆盖了 reset
    - 修复方式：在写 quota 前用 with_for_update() 重新查询，让数据库层
      对该行加排他锁，所有并发写操作强制串行执行，消除竞态。
    """
    async def _check(
        user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
    ):
        # --- 读取插件配置 ---
        try:
            cfg = importlib.import_module(f"plugins.{plugin_name}.config")
            default = getattr(cfg, "QUOTA_DEFAULT", None)
            rpm_limit = getattr(cfg, "RPM", None)
        except Exception:
            default = None
            rpm_limit = None

        # --- 1. RPM 速率限制检查（内存级，无需加 DB 锁）---
        if rpm_limit is not None:
            now = time.time()
            history = _rpm_records[user.id][plugin_name]
            # 筛选出最近 60 秒内的请求时间戳
            history = [ts for ts in history if now - ts < 60.0]

            if len(history) >= rpm_limit:
                _rpm_records[user.id][plugin_name] = history
                raise HTTPException(
                    status_code=429,
                    detail=f"Rate limit exceeded for {plugin_name}. Max {rpm_limit} requests per minute.",
                )

            # 未超限，加入当前时间戳
            history.append(now)
            _rpm_records[user.id][plugin_name] = history

        # --- 2. 重新查询并对该行加排他锁 ---
        # 关键修复：不复用 get_current_user 里的 user 对象（可能是 stale 数据），
        # 而是在当前 db session 内重新 SELECT FOR UPDATE，
        # 确保读取的是最新数据，且写入前其他事务无法并发修改同一行。
        result = await db.execute(
            select(User).where(User.id == user.id).with_for_update()
        )
        locked_user = result.scalar_one()

        # --- 3. Quota 总量检查 & 懒初始化 ---
        quota = locked_user.quota  # 通过 property 反序列化，此时是最新值
        if plugin_name not in quota:
            quota[plugin_name] = {"used": 0, "limit": default}

        entry = quota[plugin_name]
        limit = entry.get("limit")
        used  = entry.get("used", 0)

        if limit is not None and used >= limit:
            # 超限时也要释放锁（commit/rollback 均可释放 FOR UPDATE 锁）
            await db.rollback()
            raise HTTPException(
                status_code=429,
                detail=f"Quota exceeded for {plugin_name}. Used: {used}/{limit}",
            )

        # --- 4. 原子递增并写回 ---
        entry["used"] = used + 1
        quota[plugin_name] = entry
        locked_user.quota = quota          # 通过 property setter 序列化回 JSON
        flag_modified(locked_user, "quota_json")  # 显式标记 JSON 字段已变更，防止 SQLAlchemy 漏追踪
        await db.commit()                  # commit 同时释放 FOR UPDATE 锁

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
