"""
core/user.py — Self-service user endpoints: profile, usage stats, API key management.
"""
import secrets
import hashlib
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from core.database import get_db, User, ApiKey, RequestLog
from core.quota import get_current_user

router = APIRouter()


def _hash_key(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def _generate_raw_key() -> str:
    """Generate a new API key: sk- followed by 48 random hex chars."""
    return "sk-" + secrets.token_hex(24)


# ────────────────────────────────────────────
# Profile & Usage
# ────────────────────────────────────────────

@router.get("/me")
async def me(user: User = Depends(get_current_user)):
    return {
        "id": user.id,
        "username": user.username,
        "is_admin": user.is_admin,
        "created_at": user.created_at,
        "quota": user.quota,
    }


@router.get("/usage")
async def usage(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(RequestLog)
        .where(RequestLog.user_id == user.id)
        .order_by(RequestLog.created_at.desc())
        .limit(200)
    )
    logs = result.scalars().all()
    return {
        "quota": user.quota,
        "recent_logs": [
            {
                "id": l.id,
                "plugin": l.plugin,
                "endpoint": l.endpoint,
                "status_code": l.status_code,
                "created_at": l.created_at,
            }
            for l in logs
        ],
    }


# ────────────────────────────────────────────
# API Key management
# ────────────────────────────────────────────

class CreateKeyRequest(BaseModel):
    name: str = "Default Key"


@router.post("/apikeys")
async def create_api_key(
    req: CreateKeyRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Create a new API key for the current user.
    Returns the raw key ONCE — it cannot be retrieved again.
    """
    raw = _generate_raw_key()
    key_prefix = raw[:10]          # "sk-a1b2c3" — shown in UI
    key_hash   = _hash_key(raw)

    api_key = ApiKey(
        user_id=user.id,
        name=req.name,
        key_prefix=key_prefix,
        key_hash=key_hash,
    )
    db.add(api_key)
    await db.commit()
    await db.refresh(api_key)

    return {
        "id": api_key.id,
        "name": api_key.name,
        "key": raw,           # ← only time the full key is returned
        "key_prefix": key_prefix,
        "created_at": api_key.created_at,
        "warning": "Save this key now — it will not be shown again.",
    }


@router.get("/apikeys")
async def list_api_keys(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(ApiKey)
        .where(ApiKey.user_id == user.id)
        .order_by(ApiKey.created_at.desc())
    )
    keys = result.scalars().all()
    return [
        {
            "id": k.id,
            "name": k.name,
            "key_prefix": k.key_prefix,
            "is_active": k.is_active,
            "created_at": k.created_at,
            "last_used_at": k.last_used_at,
        }
        for k in keys
    ]


@router.delete("/apikeys/{key_id}")
async def revoke_api_key(
    key_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(ApiKey).where(ApiKey.id == key_id, ApiKey.user_id == user.id)
    )
    key = result.scalar_one_or_none()
    if not key:
        raise HTTPException(status_code=404, detail="API key not found")
    await db.delete(key)
    await db.commit()
    return {"deleted": key_id}


@router.patch("/apikeys/{key_id}")
async def rename_api_key(
    key_id: int,
    req: CreateKeyRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(ApiKey).where(ApiKey.id == key_id, ApiKey.user_id == user.id)
    )
    key = result.scalar_one_or_none()
    if not key:
        raise HTTPException(status_code=404, detail="API key not found")
    key.name = req.name
    await db.commit()
    return {"id": key.id, "name": key.name}