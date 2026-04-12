import copy
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from datetime import datetime
from sqlalchemy import select
from sqlalchemy.orm.attributes import flag_modified  # ← 新增

from core.ban import cleanup_request_log
from core.database import AsyncSessionLocal, User

scheduler = AsyncIOScheduler()


async def reset_all_quotas():
    print(f"🔥 [CRON] Reset quotas at {datetime.utcnow()}")

    async with AsyncSessionLocal() as db:
        result = await db.execute(select(User))
        users = result.scalars().all()

        for user in users:
            quota = copy.deepcopy(user.quota)  # ← 改这里

            for plugin in quota:
                quota[plugin]["used"] = 0

            user.quota = quota
            flag_modified(user, "quota_json")  # ← 新增这行

        await db.commit()

    print("✅ All quotas reset")


def start_scheduler():
    scheduler.add_job(
        reset_all_quotas,
        trigger="cron",
        hour=0,
        minute=0,
        timezone="Asia/Tokyo",
    )
    scheduler.add_job(cleanup_request_log, trigger="cron", hour=0, minute=0, timezone="Asia/Tokyo")
    scheduler.start()
