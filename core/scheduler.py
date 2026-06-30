"""
core/scheduler.py
"""
import copy
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from datetime import datetime, timedelta
from sqlalchemy import select, delete

from core.ban import cleanup_request_log
from core.quota import cleanup_rpm_records
from core.database import AsyncSessionLocal, User, AccessLog, get_user_quota_lock

scheduler = AsyncIOScheduler()

ACCESS_LOG_RETENTION_DAYS = 30


async def purge_old_access_logs():
    """删除超过保留期的审计日志，控制 gateway.db 体积。"""
    cutoff = datetime.utcnow() - timedelta(days=ACCESS_LOG_RETENTION_DAYS)
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            delete(AccessLog).where(AccessLog.created_at < cutoff)
        )
        await db.commit()
    print(f"🧹[CRON] Purged {result.rowcount} access_logs older than "
          f"{ACCESS_LOG_RETENTION_DAYS}d at {datetime.now()}")

async def reset_all_quotas():
    """
    将所有用户的所有插件 used 计数归零。
    """
    print(f"🔥[CRON] Reset quotas at {datetime.now()} (Local)")

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
                print(f"  ✓ user_id={user_id} quota reset")

    print("✅ All quotas reset")


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
    # 注意: 如果 cleanup_request_log 也是普通的 def 同步函数且操作内存，建议去 ban.py 里也加上 async def
    scheduler.add_job(cleanup_request_log, trigger="cron", hour=0, minute=31, timezone=tz)

    # 每 10 分钟清理 RPM 内存字典，防止空置数据堆积
    scheduler.add_job(cleanup_rpm_records, trigger="interval", minutes=10, timezone=tz)

    # 每天 03:17 清理超过保留期的审计日志
    scheduler.add_job(purge_old_access_logs, trigger="cron", hour=3, minute=17, timezone=tz)

    scheduler.start()