"""
core/quota.py — Reusable quota enforcement dependency for plugins.

Supports two authentication methods transparently:
  1. JWT Bearer token  (from /api/auth/login)
  2. API Key Bearer    (sk-xxxx, created via /api/user/apikeys)

Usage in a plugin router:
    from core.quota import require_quota, get_current_user

    @router.post("/chat")
    async def chat(
        req: ...,
        user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
        _quota: None = Depends(require_quota("openai_proxy")),
    ):
        ...
"""
import importlib, pkgutil, os, hashlib
from datetime import datetime
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from core.database import get_db, User, ApiKey, RequestLog
from core.auth_utils import decode_token

PLUGINS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "plugins")

# Use HTTPBearer so we can inspect the token ourselves
_bearer = HTTPBearer(auto_error=False)


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

        # Update last_used_at (best-effort, don't fail the request if this fails)
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
    1. Lazy-inits the user's quota entry for `plugin_name`.
    2. Checks if limit is reached (None = unlimited).
    3. Increments used count.
    """
    async def _check(
        user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
    ):
        quota = user.quota
        if plugin_name not in quota:
            try:
                cfg = importlib.import_module(f"plugins.{plugin_name}.config")
                default = getattr(cfg, "QUOTA_DEFAULT", None)
            except Exception:
                default = None
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