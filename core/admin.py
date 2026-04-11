"""
core/admin.py — Admin-only endpoints: invite codes, user listing, global stats
"""
import secrets
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from pydantic import BaseModel

from core.database import get_db, User, InviteCode, RequestLog
from core.quota import get_current_admin

router = APIRouter()

# ---------- Invite Codes ----------

@router.post("/invite/generate")
async def generate_invite(
    count: int = 1,
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    codes = []
    for _ in range(count):
        code = secrets.token_urlsafe(24)
        invite = InviteCode(code=code, created_by=admin.username)
        db.add(invite)
        codes.append(code)
    await db.commit()
    return {"codes": codes}

@router.get("/invite/list")
async def list_invites(
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(InviteCode))
    invites = result.scalars().all()
    return [{"code": i.code, "created_at": i.created_at, "created_by": i.created_by} for i in invites]

@router.delete("/invite/{code}")
async def delete_invite(
    code: str,
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(InviteCode).where(InviteCode.code == code))
    invite = result.scalar_one_or_none()
    if not invite:
        raise HTTPException(status_code=404, detail="Invite code not found")
    await db.delete(invite)
    await db.commit()
    return {"deleted": code}

# ---------- User Management ----------

@router.get("/users")
async def list_users(
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(User))
    users = result.scalars().all()
    return [
        {
            "id": u.id,
            "username": u.username,
            "is_admin": u.is_admin,
            "created_at": u.created_at,
            "quota": u.quota,
        }
        for u in users
    ]

class QuotaUpdateRequest(BaseModel):
    plugin: str
    limit: int | None  # None = unlimited

@router.post("/users/{user_id}/quota")
async def update_user_quota(
    user_id: int,
    req: QuotaUpdateRequest,
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    quota = user.quota
    if req.plugin not in quota:
        quota[req.plugin] = {"used": 0, "limit": req.limit}
    else:
        quota[req.plugin]["limit"] = req.limit
    user.quota = quota
    await db.commit()
    return {"quota": user.quota}

@router.post("/users/{user_id}/reset-quota")
async def reset_user_quota(
    user_id: int,
    plugin: str,
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    quota = user.quota
    if plugin in quota:
        quota[plugin]["used"] = 0
    user.quota = quota
    await db.commit()
    return {"quota": user.quota}

@router.post("/users/{user_id}/set-admin")
async def set_admin(
    user_id: int,
    is_admin: bool,
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    user.is_admin = is_admin
    await db.commit()
    return {"user_id": user_id, "is_admin": is_admin}

# ---------- Global Stats ----------

@router.get("/stats")
async def global_stats(
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    total_users = (await db.execute(select(func.count(User.id)))).scalar()
    total_requests = (await db.execute(select(func.count(RequestLog.id)))).scalar()

    # Requests per plugins
    plugin_rows = (await db.execute(
        select(RequestLog.plugin, func.count(RequestLog.id))
        .group_by(RequestLog.plugin)
    )).all()

    # Requests per user
    user_rows = (await db.execute(
        select(User.username, func.count(RequestLog.id))
        .join(RequestLog, User.id == RequestLog.user_id, isouter=True)
        .group_by(User.username)
    )).all()

    # Last 30 daily totals
    from sqlalchemy import text
    daily_rows = (await db.execute(text(
        "SELECT date(created_at) as day, count(*) as cnt FROM request_logs "
        "GROUP BY day ORDER BY day DESC LIMIT 30"
    ))).all()

    return {
        "total_users": total_users,
        "total_requests": total_requests,
        "by_plugin": [{"plugins": r[0], "count": r[1]} for r in plugin_rows],
        "by_user": [{"username": r[0], "count": r[1]} for r in user_rows],
        "daily": [{"day": r[0], "count": r[1]} for r in reversed(daily_rows)],
    }
