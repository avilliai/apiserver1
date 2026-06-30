"""
core/admin.py — Admin-only endpoints: invite codes, user listing, global stats
"""
import re
import secrets
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, or_, distinct
from pydantic import BaseModel

from core.database import get_db, User, InviteCode, RequestLog, AccessLog, BannedIp
from core.quota import get_current_admin
from core.access_log import add_banned_ips, remove_banned_ip
from core.auth import build_default_quota

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
            "is_banned": bool(u.is_banned),
            "ban_reason": u.ban_reason,
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
    # 统计改用 access_logs（中间件全量记录，含流式），比 request_logs 更准确。
    # 代价：仅有中间件上线以来的数据，更早历史不计入。
    total_requests = (await db.execute(select(func.count(AccessLog.id)))).scalar()

    # Requests per plugin（按量降序）
    plugin_rows = (await db.execute(
        select(AccessLog.plugin, func.count(AccessLog.id))
        .group_by(AccessLog.plugin)
        .order_by(func.count(AccessLog.id).desc())
    )).all()

    # Requests per (registered) user
    user_rows = (await db.execute(
        select(User.username, func.count(AccessLog.id))
        .join(AccessLog, User.id == AccessLog.user_id, isouter=True)
        .group_by(User.username)
    )).all()

    # Last 30 daily totals
    from sqlalchemy import text
    daily_rows = (await db.execute(text(
        "SELECT date(created_at) as day, count(*) as cnt FROM access_logs "
        "GROUP BY day ORDER BY day DESC LIMIT 30"
    ))).all()

    return {
        "total_users": total_users,
        "total_requests": total_requests,
        "by_plugin": [{"plugin": r[0] or "unknown", "count": r[1]} for r in plugin_rows],
        "by_user": [{"username": r[0], "count": r[1]} for r in user_rows],
        "daily": [{"day": r[0], "count": r[1]} for r in reversed(daily_rows)],
    }


# ---------- Request Logs（中间件审计日志）检索 ----------

@router.get("/logs")
async def list_access_logs(
    search: str = "",
    plugin: str = "",
    user_id: int | None = None,
    ip: str = "",
    limit: int = 50,
    offset: int = 0,
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """
    检索中间件记录的请求日志。关键字 search 支持三种模式：
    · "user: 用户名" → 精确(大小写不敏感)匹配该用户名的全部请求记录；
    · "ip: 地址"     → 精确匹配该 IP 的全部请求记录；
    · 其它           → 在用户名/IP/接口/插件/请求体/响应体上做大小写不敏感模糊匹配。
    返回的中文为可读文本（FastAPI 默认 ensure_ascii=False）。
    """
    limit = max(1, min(limit, 200))
    offset = max(0, offset)

    base = select(AccessLog)
    if search:
        # 前缀语法 "user: xxx" / "ip: xxx" 切换为对应字段的精确过滤；其余照旧模糊匹配。
        m = re.match(r"\s*(user|ip)\s*:\s*(.+?)\s*$", search, re.IGNORECASE)
        if m and m.group(1).lower() == "user":
            base = base.where(AccessLog.username.ilike(m.group(2)))
        elif m:
            base = base.where(AccessLog.ip_address.ilike(m.group(2)))
        else:
            kw = f"%{search}%"
            base = base.where(or_(
                AccessLog.username.ilike(kw),
                AccessLog.ip_address.ilike(kw),
                AccessLog.endpoint.ilike(kw),
                AccessLog.plugin.ilike(kw),
                AccessLog.request_body.ilike(kw),
                AccessLog.response_body.ilike(kw),
            ))
    if plugin:
        base = base.where(AccessLog.plugin == plugin)
    if user_id is not None:
        base = base.where(AccessLog.user_id == user_id)
    if ip:
        base = base.where(AccessLog.ip_address == ip)

    total = (await db.execute(
        select(func.count()).select_from(base.subquery())
    )).scalar()

    rows = (await db.execute(
        base.order_by(AccessLog.created_at.desc()).limit(limit).offset(offset)
    )).scalars().all()

    # 附带每个用户当前的封禁状态，供前端按钮显示 Ban / Unban
    uids = {r.user_id for r in rows if r.user_id}
    ban_map = {}
    if uids:
        urows = (await db.execute(
            select(User.id, User.is_banned).where(User.id.in_(uids))
        )).all()
        ban_map = {uid: bool(b) for uid, b in urows}

    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "logs": [
            {
                "id": r.id,
                "user_id": r.user_id,
                "username": r.username,
                "user_banned": ban_map.get(r.user_id, False),
                "ip_address": r.ip_address,
                "method": r.method,
                "plugin": r.plugin,
                "endpoint": r.endpoint,
                "status_code": r.status_code,
                "request_body": r.request_body,
                "response_body": r.response_body,
                "api_key_prefix": r.api_key_prefix,
                "duration_ms": r.duration_ms,
                "created_at": r.created_at,
            }
            for r in rows
        ],
    }


# ---------- 一键封禁 / 解封 ----------

class BanRequest(BaseModel):
    reason: str = ""
    ip: str | None = None


@router.post("/users/{user_id}/ban")
async def ban_user(
    user_id: int,
    req: BanRequest,
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """
    封禁用户：标记 is_banned + 把其所有接口配额上限设为 0 + 封禁其 IP
    （传入的 ip 及该用户在 access_logs 中出现过的所有 IP）。
    """
    user = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    reason = req.reason or "banned by admin"

    # 1) 标记封禁状态
    user.is_banned = True
    user.banned_at = datetime.utcnow()
    user.ban_reason = reason

    # 2) 所有接口配额上限 → 0（后续调用立即 429）
    quota = user.quota
    for plugin in quota:
        quota[plugin]["limit"] = 0
    user.quota = quota

    # 3) 收集要封的 IP = 传入 ip + 该用户历史出现过的所有 IP
    ips = set()
    if req.ip:
        ips.add(req.ip)
    log_ips = (await db.execute(
        select(distinct(AccessLog.ip_address)).where(AccessLog.user_id == user_id)
    )).scalars().all()
    ips.update(ip for ip in log_ips if ip)

    existing = set()
    if ips:
        existing = set((await db.execute(
            select(BannedIp.ip_address).where(BannedIp.ip_address.in_(ips))
        )).scalars().all())
    for ip in ips:
        if ip and ip not in existing:
            db.add(BannedIp(ip_address=ip, user_id=user_id, reason=reason))

    await db.commit()

    # 4) 立即更新内存封禁集
    add_banned_ips(ips)

    return {
        "user_id": user_id,
        "is_banned": True,
        "banned_ips": sorted(ips),
        "zeroed_plugins": list(quota.keys()),
    }


@router.post("/users/{user_id}/unban")
async def unban_user(
    user_id: int,
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """
    解封：清除封禁标记 + 把各接口配额上限还原为对应插件默认值（保留 used）+
    删除该用户的被封 IP 记录。
    """
    user = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    user.is_banned = False
    user.banned_at = None
    user.ban_reason = None

    # 配额上限还原为各插件默认（保留已用次数）
    defaults = build_default_quota()  # {name: {"used":0, "limit": QUOTA_DEFAULT}}
    quota = user.quota
    for plugin, entry in quota.items():
        if plugin in defaults:
            entry["limit"] = defaults[plugin]["limit"]
    user.quota = quota

    # 删除该用户的 banned_ips 行并从内存集移除
    ip_rows = (await db.execute(
        select(BannedIp).where(BannedIp.user_id == user_id)
    )).scalars().all()
    removed = [row.ip_address for row in ip_rows]
    for row in ip_rows:
        await db.delete(row)

    await db.commit()

    for ip in removed:
        remove_banned_ip(ip)

    return {
        "user_id": user_id,
        "is_banned": False,
        "unbanned_ips": removed,
        "restored_limits": {p: quota[p]["limit"] for p in quota},
    }
