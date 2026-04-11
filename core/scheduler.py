from apscheduler.schedulers.asyncio import AsyncIOScheduler
from datetime import datetime
from sqlalchemy import select

from core.database import AsyncSessionLocal, User

scheduler = AsyncIOScheduler()


async def reset_all_quotas():
    print(f"🔥 [CRON] Reset quotas at {datetime.utcnow()}")

    async with AsyncSessionLocal() as db:
        result = await db.execute(select(User))
        users = result.scalars().all()

        for user in users:
            quota = user.quota or {}

            # 🔥 核心：所有 plugin 全部清零
            for plugin in quota:
                quota[plugin]["used"] = 0

            user.quota = quota

        await db.commit()

    print("✅ All quotas reset")


def start_scheduler():
    scheduler.add_job(
        reset_all_quotas,
        trigger="cron",
        hour=0,
        minute=0,
        timezone="Asia/Tokyo",  # 你现在在日本
    )
    scheduler.start()