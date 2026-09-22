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

# 默认保留最近 3 天日志，可通过环境变量 LOG_RETENTION_DAYS 或 ACCESS_LOG_RETENTION_DAYS 覆盖
# 作用于 access_logs 与 request_logs 两张日志表
LOG_RETENTION_DAYS = int(
    os.getenv("LOG_RETENTION_DAYS")
    or os.getenv("ACCESS_LOG_RETENTION_DAYS")
    or 3
)
# 最大日志行数安全兜底（超过上限时按主键自增顺序保留最新行）
MAX_LOG_ROWS = int(os.getenv("MAX_LOG_ROWS", "100000"))


async def purge_old_logs(retention_days: int = None):
    """
    清理旧的审计日志 (AccessLog) 与请求日志 (RequestLog)。
    清理后执行 SQLite incremental_vacuum 及时收缩并释放 gateway.db 空间。
    """
    days = retention_days if retention_days is not None else LOG_RETENTION_DAYS
    cutoff = datetime.utcnow() - timedelta(days=days)
    purged_access = 0
    purged_request = 0

    async with AsyncSessionLocal() as db:
        # 1. 清理超期 AccessLog
        res1 = await db.execute(
            delete(AccessLog).where(AccessLog.created_at < cutoff)
        )
        purged_access = res1.rowcount or 0

        # 2. 清理超期 RequestLog
        res2 = await db.execute(
            delete(RequestLog).where(RequestLog.created_at < cutoff)
        )
        purged_request = res2.rowcount or 0

        # 3. 最大行数兜底（双重保障防止日志无限膨胀）
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

        # 4. 整理 SQLite 碎片空间
        if purged_access > 0 or purged_request > 0:
            try:
                await db.execute(text("PRAGMA incremental_vacuum(500)"))
            except Exception as e:
                logger.warning(f"incremental_vacuum failed: {e}")

    logger.info(
        f"🧹[LOG] Purged {purged_access} access_logs and {purged_request} request_logs older than {days}d at {datetime.now()}"
    )
    return {
        "purged_access_logs": purged_access,
        "purged_request_logs": purged_request,
        "retention_days": days,
    }


# 向后兼容别名
async def purge_old_access_logs():
    return await purge_old_logs()


async def reset_all_quotas():
    """
    将所有用户的所有插件 used 计数归零。
    """
    logger.info(f"🔥[CRON] Reset quotas at {datetime.now()} (Local)")

    # 第一步：查出所有用户 ID（不加业务锁，避免慢查询影响持锁时间）
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(User.id))
        user_ids = result.scalars().all()

    # 第二步：逐用户加锁 → 加载 → 归零 → 提交
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

                # 触发 @quota.setter，正确标记 dirty
                user.quota = new_quota

                await db.commit()
                logger.info(f"  ✓ user_id={user_id} quota reset")

    logger.info("✅ All quotas reset")


def start_scheduler():
    # 强制指定时区为北京时间，防止服务器默认 UTC 导致定时任务在中午 12:01 才触发
    tz = "Asia/Shanghai"

    # 每天 04:01 重置配额
    scheduler.add_job(
        reset_all_quotas,
        trigger="cron",
        hour=4,
        minute=1,
        timezone=tz
    )
    # 每天 00:31 清理 ban.py 内存日志
    scheduler.add_job(cleanup_request_log, trigger="cron", hour=0, minute=31, timezone=tz)

    # 每 10 分钟清理 RPM 内存字典，防止空置数据堆积
    scheduler.add_job(cleanup_rpm_records, trigger="interval", minutes=10, timezone=tz)

    # 每天 03:17 清理超过保留期的审计日志与请求日志并整理 SQLite 碎片
    scheduler.add_job(purge_old_logs, trigger="cron", hour=3, minute=17, timezone=tz)

    scheduler.start()
