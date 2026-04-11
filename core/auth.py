"""
core/auth.py — Registration (invite-code gated), Login
"""
import importlib, pkgutil, os
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel

from core.database import get_db, User, InviteCode
from core.auth_utils import hash_password, verify_password, create_token

router = APIRouter()

PLUGINS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "plugins")

def build_default_quota() -> dict:
    """
    Scan all plugins and build a fresh default quota dict.
    Called when a new user registers, so new plugins auto-apply too.
    """
    quota = {}
    for finder, name, ispkg in pkgutil.iter_modules([PLUGINS_DIR]):
        if not ispkg:
            continue
        try:
            cfg = importlib.import_module(f"plugins.{name}.config")
            default = getattr(cfg, "QUOTA_DEFAULT", None)
            quota[name] = {"used": 0, "limit": default}
        except Exception:
            pass
    return quota

# ---------- Schemas ----------

class RegisterRequest(BaseModel):
    username: str
    password: str
    invite_code: str

class LoginRequest(BaseModel):
    username: str
    password: str

# ---------- Endpoints ----------

@router.post("/register")
async def register(req: RegisterRequest, db: AsyncSession = Depends(get_db)):
    # 1. Validate invite code
    result = await db.execute(select(InviteCode).where(InviteCode.code == req.invite_code))
    invite = result.scalar_one_or_none()
    if not invite:
        raise HTTPException(status_code=400, detail="Invalid or already-used invite code")

    # 2. Check username uniqueness
    existing = await db.execute(select(User).where(User.username == req.username))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Username already taken")

    # 3. Create user with default quotas from all plugins
    default_quota = build_default_quota()
    user = User(
        username=req.username,
        hashed_password=hash_password(req.password),
    )
    user.quota = default_quota

    db.add(user)

    # 4. Destroy invite code immediately
    await db.delete(invite)

    await db.commit()
    await db.refresh(user)

    token = create_token({"sub": str(user.id), "username": user.username, "is_admin": user.is_admin})
    return {"access_token": token, "token_type": "bearer", "username": user.username, "is_admin": user.is_admin}


@router.post("/login")
async def login(req: LoginRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.username == req.username))
    user = result.scalar_one_or_none()
    if not user or not verify_password(req.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Incorrect username or password")

    # Lazily patch quota for any plugins added since this user registered
    quota = user.quota
    changed = False
    for finder, name, ispkg in pkgutil.iter_modules([PLUGINS_DIR]):
        if not ispkg:
            continue
        if name not in quota:
            try:
                cfg = importlib.import_module(f"plugins.{name}.config")
                default = getattr(cfg, "QUOTA_DEFAULT", None)
                quota[name] = {"used": 0, "limit": default}
                changed = True
            except Exception:
                pass
    if changed:
        user.quota = quota
        await db.commit()

    token = create_token({"sub": str(user.id), "username": user.username, "is_admin": user.is_admin})
    return {"access_token": token, "token_type": "bearer", "username": user.username, "is_admin": user.is_admin}
