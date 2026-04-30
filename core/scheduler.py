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
    """
    将所有用户的所有插件 used 计数归零。

    与 WebUI（admin.py reset_user_quota）保持完全相同的写法：
      1. SELECT ... FOR UPDATE 加行锁
      2. 通过 @property 读出 quota dict
      3. 修改后重新赋值（触发 @quota.setter 更新 quota_json）
      4. 用 flag_modified 显式告知 SQLAlchemy 该列已变更
         （原地修改 dict 内容后再赋回，ORM 有时无法自动检测到变化）
      5. commit

    WebUI 每次都能成功的原因正是 flag_modified 确保了脏标记，
    scheduler 之前缺少这一步导致 commit 时 SQLAlchemy 认为列未变更而跳过写库。
    """
    print(f"🔥 [CRON] Reset quotas at {datetime.utcnow()}")

    async with AsyncSessionLocal() as db:
        result = await db.execute(select(User).with_for_update())
        users = result.scalars().all()

        for user in users:
            quota = user.quota  # @property 解析 JSON，得到最新数据
            if not quota:
                continue

            for plugin in quota:
                quota[plugin]["used"] = 0

            # 赋值触发 @quota.setter，将 dict 序列化回 quota_json
            user.quota = quota

            # 关键：显式标记 quota_json 列为已修改。
            # SQLAlchemy 对 Text 列做原地内容变更检测时依赖对象标识，
            # 若 setter 序列化后的字符串与 ORM 内部跟踪的旧值引用相同，
            # 有时不会自动标记 dirty，导致 commit 时跳过该行的 UPDATE。
            flag_modified(user, "quota_json")

        await db.commit()

    print("✅ All quotas reset")


def start_scheduler():
    # 每天 04:01 重置配额
    scheduler.add_job(
        reset_all_quotas,
        trigger="cron",
        hour=12,
        minute=5,
    )
    # 每天 00:31 清理 ban.py 内存日志
    scheduler.add_job(cleanup_request_log, trigger="cron", hour=0, minute=31)

    # 每 10 分钟清理 RPM 内存字典，防止空置数据堆积
    scheduler.add_job(cleanup_rpm_records, trigger="interval", minutes=10)

    scheduler.start()