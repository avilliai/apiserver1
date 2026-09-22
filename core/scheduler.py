"""
core/scheduler.py
"""
import copy
import logging
import os
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from datetime import datetime, timedelta
from sqlalchemy import select, delete, text

from core.ban import cleanup_request_log
from core.quota import cleanup_rpm_records
from core.database import AsyncSessionLocal, User, AccessLog, RequestLog, get_user_quota_lock

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler()

# ??????????? 7 ????????? LOG_RETENTION_DAYS ? ACCESS_LOG_RETENTION_DAYS ???
# ?????? access_logs ? request_logs ??????
LOG_RETENTION_DAYS = int(
    os.getenv("LOG_RETENTION_DAYS")
    or os.getenv("ACCESS_LOG_RETENTION_DAYS")
    or 7
)
# ????????????????????????????????? MAX_LOG_ROWS ??????????????
MAX_LOG_ROWS = int(os.getenv("MAX_LOG_ROWS", "100000"))


async def purge_old_logs(retention_days: int = None):
    """
    ???????????? (AccessLog) ??????? (RequestLog)?
    ??????? SQLite incremental_vacuum ??????????? gateway.db ???
    """
    days = retention_days if retention_days is not None else LOG_RETENTION_DAYS
    cutoff = datetime.utcnow() - timedelta(days=days)
    purged_access = 0
    purged_request = 0

    async with AsyncSessionLocal() as db:
        # 1. ????? AccessLog
        res1 = await db.execute(
            delete(AccessLog).where(AccessLog.created_at < cutoff)
        )
        purged_access = res1.rowcount or 0

        # 2. ????? RequestLog
        res2 = await db.execute(
            delete(RequestLog).where(RequestLog.created_at < cutoff)
        )
        purged_request = res2.rowcount or 0

        # 3. ???????? (????????????????)
        if MAX_LOG_ROWS > 0:
            acc_ids = (await db.execute(select(AccessLog.id).order_by(AccessLog.id.desc()))).scalars().all()
            if len(acc_ids) > MAX_LOG_ROWS:
                threshold_id = acc_ids[MAX_LOG_ROWS - 1]
                del_res = await db.execute(delete(AccessLog).where(AccessLog.id < threshold_id))
                purged_access += (del_res.rowcount or 0)

            req_ids = (await db.execute(select(RequestLog.id).order_by(RequestLog.id.desc()))).scalars().all()
            if len(req_ids) > MAX_LOG_ROWS:
                threshold_id = req_ids[MAX_LOG_ROWS - 1]
                del_res = await db.execute(delete(RequestLog).where(RequestLog.id < threshold_id))
                purged_request += (del_res.rowcount or 0)

        await db.commit()

        # 4. ?? SQLite ????
        if purged_access > 0 or purged_request > 0:
            try:
                await db.execute(text("PRAGMA incremental_vacuum(500)"))
            except Exception as e:
                logger.warning(f"incremental_vacuum failed: {e}")

    logger.info(
        f"??[CRON] Purged {purged_access} access_logs and {purged_request} request_logs older than {days}d at {datetime.now()}"
    )
    return {
        "purged_access_logs": purged_access,
        "purged_request_logs": purged_request,
        "retention_days": days,
    }


# ???????
async def purge_old_access_logs():
    return await purge_old_logs()


async def reset_all_quotas():
    """
    ?????????? used ?????
    """
    logger.info(f"??[CRON] Reset quotas at {datetime.now()} (Local)")

    # ?????????? ID???????????????????
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(User.id))
        user_ids = result.scalars().all()

    # ????????? ? ?? ? ?? ? ??
    for user_id in user_ids:
        quota_lock = await get_user_quota_lock(user_id)
        async with quota_lock:
            async with AsyncSessionLocal() as db:
                result = await db.execute(select(User).where(User.id == user_id))
                user = result.scalar_one_or_none()
                if user is None:
                    continue

                old_quota = user.quota
                if not old_quota:
                    continue

                new_quota = copy.deepcopy(old_quota)
                for plugin in new_quota:
                    new_quota[plugin]["used"] = 0

                # ?? @quota.setter????? dirty
                user.quota = new_quota

                await db.commit()
                logger.info(f"  ? user_id={user_id} quota reset")

    logger.info("? All quotas reset")


def start_scheduler():
    # ??????????????????? UTC ????????? 12:01 ???
    tz = "Asia/Shanghai"

    # ?? 04:01 ????
    scheduler.add_job(
        reset_all_quotas,
        trigger="cron",
        hour=4,
        minute=1,
        timezone=tz
    )
    # ?? 00:31 ?? ban.py ????
    scheduler.add_job(cleanup_request_log, trigger="cron", hour=0, minute=31, timezone=tz)

    # ? 10 ???? RPM ?????????????
    scheduler.add_job(cleanup_rpm_records, trigger="interval", minutes=10, timezone=tz)

    # ?? 03:17 ??????????????????????? SQLite ????
    scheduler.add_job(purge_old_logs, trigger="cron", hour=3, minute=17, timezone=tz)

    scheduler.start()
