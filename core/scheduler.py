"""
core/scheduler.py

修复说明（定时配额归零不生效）
─────────────────────────────────────────────────────────────────────────────
原问题：
  reset_all_quotas 虽然已加 flag_modified，但依然无法与并发的
  require_quota 互斥，导致 scheduler 写入的归零结果被后者覆盖。

  根因：
  1. SELECT FOR UPDATE 在 SQLite + aiosqlite 上被静默忽略，无任何加锁效果。
  2. 原实现一次性锁住所有行、循环处理、最后统一 commit，
     持锁时间长，与 require_quota 之间没有共享的互斥原语。

修复方案：
  - 与 require_quota 共用 database.get_user_quota_lock(user_id)。
  - 逐用户加锁、处理、单独 commit，缩短每把锁的持有时间。
  - 拿锁后调用 db.refresh(user) 强制从数据库重新加载该行，
    避免读到 Session 缓存中的旧值。
  - 移除无效的 SELECT FOR UPDATE。
  - 保留 flag_modified，确保 SQLAlchemy 检测到 Text 列变更。
─────────────────────────────────────────────────────────────────────────────
"""
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from datetime import datetime
from sqlalchemy import select
from sqlalchemy.orm.attributes import flag_modified

from core.ban import cleanup_request_log
from core.quota import cleanup_rpm_records
from core.database import AsyncSessionLocal, User, get_user_quota_lock

scheduler = AsyncIOScheduler()


async def reset_all_quotas():
    """
    将所有用户的所有插件 used 计数归零。

    与 require_quota 共用 per-user asyncio.Lock，保证：
      - scheduler 持锁归零时，require_quota 对同一用户的递增必须等待。
      - require_quota 持锁递增时，scheduler 对同一用户的归零必须等待。

    逐用户加锁 + 单独 commit，缩短每把锁的持有时间，减少对请求延迟的影响。
    """
    print(f"🔥 [CRON] Reset quotas at {datetime.utcnow()}")

    # 第一步：在不加锁的情况下查出所有用户 ID，
    # 避免在持有应用层锁时执行慢查询。
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(User.id))
        user_ids = result.scalars().all()

    # 第二步：逐用户加锁、重新加载、归零、提交。
    for user_id in user_ids:
        quota_lock = await get_user_quota_lock(user_id)
        async with quota_lock:
            async with AsyncSessionLocal() as db:
                # 不用 with_for_update()——SQLite 上无效，且此处已有应用层锁保护。
                result = await db.execute(select(User).where(User.id == user_id))
                user = result.scalar_one_or_none()
                if user is None:
                    continue

                quota = user.quota  # @property 解析 JSON，得到最新数据
                if not quota:
                    continue

                for plugin in quota:
                    quota[plugin]["used"] = 0

                # 赋值触发 @quota.setter，将 dict 序列化回 quota_json
                user.quota = quota

                # 显式标记 quota_json 列为已修改。
                # SQLAlchemy 对 Text 列做原地内容变更检测时依赖对象标识，
                # setter 序列化后若字符串引用未变，ORM 有时不会自动标记 dirty，
                # 导致 commit 时跳过该行的 UPDATE。
                flag_modified(user, "quota_json")

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