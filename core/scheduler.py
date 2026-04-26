import copy
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from datetime import datetime
from sqlalchemy import select
from sqlalchemy.orm.attributes import flag_modified

from core.ban import cleanup_request_log
from core.quota import cleanup_rpm_records  # ← 新增引入
from core.database import AsyncSessionLocal, User

scheduler = AsyncIOScheduler()


async def reset_all_quotas():
    print(f"🔥 [CRON] Reset quotas at {datetime.utcnow()}")

    async with AsyncSessionLocal() as db:
        result = await db.execute(select(User))
        users = result.scalars().all()

        for user in users:
            quota = copy.deepcopy(user.quota)

            for plugin in quota:
                quota[plugin]["used"] = 0

            user.quota = quota
            flag_modified(user, "quota_json")

        await db.commit()

    print("✅ All quotas reset")


def start_scheduler():
    scheduler.add_job(
        reset_all_quotas,
        trigger="cron",
        hour=4,
        minute=1,
    )
    # 原本每天清理 ban.py 内存日志，这里维持不变
    scheduler.add_job(cleanup_request_log, trigger="cron", hour=0, minute=31)

    # ← 新增：每隔10分钟清理一次 rate_limit(RPM) 的内存字典，防止空置数据堆积
    scheduler.add_job(cleanup_rpm_records, trigger="interval", minutes=10)

    scheduler.start()