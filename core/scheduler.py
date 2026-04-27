import copy
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from datetime import datetime
from sqlalchemy import select
from sqlalchemy.orm.attributes import flag_modified

from core.ban import cleanup_request_log
from core.quota import cleanup_rpm_records
from core.database import AsyncSessionLocal, User

scheduler = AsyncIOScheduler()


async def reset_all_quotas():
    print(f"🔥 [CRON] Reset quotas at {datetime.utcnow()}")
    async with AsyncSessionLocal() as db:
        # 关键修复：用 with_for_update() 对所有用户行加排他锁。
        # 与 require_quota 里的 SELECT FOR UPDATE 互斥，
        # 确保 reset 期间没有并发请求能同时修改 quota_json，
        # 彻底消除「reset 写入 used=0 被后续请求的 stale 写覆盖」的竞态。
        result = await db.execute(select(User).with_for_update())
        users = result.scalars().all()

        for user in users:
            quota = copy.deepcopy(user.quota)
            for plugin in quota:
                quota[plugin]["used"] = 0
            user.quota = quota
            flag_modified(user, "quota_json")  # 显式标记，防止 SQLAlchemy 漏追踪 JSON 变更

        await db.commit()  # commit 同时释放所有行锁
    print("✅ All quotas reset")


def start_scheduler():
    scheduler.add_job(
        reset_all_quotas,
        trigger="cron",
        hour=4,
        minute=1,
    )
    # 每天清理 ban.py 内存日志
    scheduler.add_job(cleanup_request_log, trigger="cron", hour=0, minute=31)
    # 每隔 10 分钟清理 RPM 内存字典，防止空置数据堆积
    scheduler.add_job(cleanup_rpm_records, trigger="interval", minutes=10)
    scheduler.start()
