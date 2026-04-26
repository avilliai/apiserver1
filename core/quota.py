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
    empty_users =[]
    for user_id, plugins_history in _rpm_records.items():
        empty_plugins =[]
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
    2. Lazy-inits the user's quota entry for `plugin_name`.
    3. Checks if global quota limit is reached (None = unlimited total).
    4. Increments used count.
    """
    async def _check(
        user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
    ):
        try:
            cfg = importlib.import_module(f"plugins.{plugin_name}.config")
            default = getattr(cfg, "QUOTA_DEFAULT", None)
            rpm_limit = getattr(cfg, "RPM", None)
        except Exception:
            default = None
            rpm_limit = None

        # --- 1. RPM 速率限制检查 ---
        if rpm_limit is not None:
            now = time.time()
            history = _rpm_records[user.id][plugin_name]
            # 筛选出最近 60 秒内的请求时间戳
            history =[ts for ts in history if now - ts < 60.0]

            if len(history) >= rpm_limit:
                _rpm_records[user.id][plugin_name] = history  # 回写更新以清理旧记录
                raise HTTPException(
                    status_code=429,
                    detail=f"Rate limit exceeded for {plugin_name}. Max {rpm_limit} requests per minute.",
                )

            # 未超限，加入当前时间戳
            history.append(now)
            _rpm_records[user.id][plugin_name] = history
        # ---------------------------

        # --- 2. Quota 总量检查 ---
        quota = user.quota
        if plugin_name not in quota:
            quota[plugin_name] = {"used": 0, "limit": default}

        entry = quota[plugin_name]
        limit = entry.get("limit")
        used  = entry.get("used", 0)

        if limit is not None and used >= limit:
            raise HTTPException(
                status_code=429,
                detail=f"Quota exceeded for {plugin_name}. Used: {used}/{limit}",
            )

        entry["used"] = used + 1
        quota[plugin_name] = entry
        user.quota = quota
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