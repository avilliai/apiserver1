import copy
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from datetime import datetime
from sqlalchemy import select

from core.ban import cleanup_request_log
from core.quota import cleanup_rpm_records
from core.database import AsyncSessionLocal, User

scheduler = AsyncIOScheduler()


async def reset_all_quotas():
    """
    将所有用户的所有插件 used 计数归零。

    修复：使用 with_for_update() 加行锁后再修改，避免与并发请求的
    require_quota 产生写-写冲突（两者都先读后写同一行）。

    注意：SQLite 不支持真正的行级锁（会退化为表锁），在 PostgreSQL/MySQL
    下此锁能精确保护单行；SQLite 下相当于序列化整个事务，行为仍然正确。
    """
    print(f"🔥 [CRON] Reset quotas at {datetime.utcnow()}")

    async with AsyncSessionLocal() as db:
        # with_for_update() 确保在我们读出并写回期间，
        # 没有其他事务能同时修改这些行。
        result = await db.execute(select(User).with_for_update())
        users = result.scalars().all()

        for user in users:
            quota = user.quota          # @property 解析 JSON
            if not quota:
                continue

            for plugin in quota:
                quota[plugin]["used"] = 0

            # 直接赋值触发 @quota.setter，SQLAlchemy 会自动标记脏值，
            # 无需再手动调用 flag_modified。
            user.quota = quota

        await db.commit()

    print("✅ All quotas reset")


def start_scheduler():
    # 每天 04:01 重置配额
    scheduler.add_job(
        reset_all_quotas,
        trigger="cron",
        hour=4,
        minute=1,
    )
    # 每天 00:31 清理 ban.py 内存日志
    scheduler.add_job(cleanup_request_log, trigger="cron", hour=0, minute=31)

    # 每 10 分钟清理 RPM 内存字典，防止空置数据堆积
    scheduler.add_job(cleanup_rpm_records, trigger="interval", minutes=10)

    scheduler.start()