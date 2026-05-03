"""
core/scheduler.py

修复说明（定时配额归零不生效）
─────────────────────────────────────────────────────────────────────────────
根因分析（最终版）：

  前端 reset-quota 端点（总是生效）的写法：
      quota[plugin]["used"] = 0
      user.quota = quota   ← setter 将 dict 序列化为新 JSON 字符串并赋给 quota_json
      await db.commit()    ← SQLAlchemy 检测到 quota_json 字符串引用已变，标记 dirty，写库

  旧 scheduler 的写法（不生效）多了一行：
      flag_modified(user, "quota_json")

  问题在于 flag_modified 传入的列名 "quota_json" 若与 ORM 模型中
  实际定义的属性名不一致，调用会静默失败——不抛异常，但也不会
  正确标记 dirty，commit 时跳过 UPDATE。

  此外，即使列名正确，旧代码在 setter 已经生成新字符串对象的前提下，
  flag_modified 是冗余的；但若 setter 实现有缺陷导致新旧字符串引用
  相同，flag_modified 才是救命稻草——两者同时依赖，反而掩盖了
  究竟是哪一侧出了问题。

修复方案（仿照前端生效的 reset-quota 写法）：
  1. 去掉 flag_modified，完全依赖 setter 生成新字符串对象触发 dirty tracking。
  2. 用 import copy 做深拷贝，保证修改后的 dict 与 getter 返回的原始对象
     不共享引用，setter 拿到的是全新对象，序列化结果必然是新字符串。
  3. 其余并发安全机制（per-user asyncio.Lock、expire_all、逐用户 commit）保持不变。
─────────────────────────────────────────────────────────────────────────────
"""
import copy
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from datetime import datetime
from sqlalchemy import select

from core.ban import cleanup_request_log
from core.quota import cleanup_rpm_records
from core.database import AsyncSessionLocal, User, get_user_quota_lock

scheduler = AsyncIOScheduler()


async def reset_all_quotas():
    """
    将所有用户的所有插件 used 计数归零。

    完全仿照前端 reset-quota 端点的写法（已验证生效）：
      quota[plugin]["used"] = 0
      user.quota = quota
      await db.commit()

    并发安全：与 require_quota 共用 per-user asyncio.Lock。
    """
    print(f"🔥 [CRON] Reset quotas at {datetime.utcnow()}")

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

                # @property getter 每次都解析 JSON 返回新 dict
                old_quota = user.quota
                if not old_quota:
                    continue

                # 深拷贝，保证修改后的对象与 getter 返回值不共享引用。
                # setter 拿到新 dict → 序列化为新字符串 → SQLAlchemy 检测到
                # quota_json 的字符串引用已变 → 正确标记 dirty → commit 写库。
                new_quota = copy.deepcopy(old_quota)
                for plugin in new_quota:
                    new_quota[plugin]["used"] = 0

                # 触发 @quota.setter，将 new_quota 序列化写入 quota_json
                user.quota = new_quota

                # ↑ 与前端 reset-quota 端点完全相同的三行操作，不再依赖
                #   flag_modified（其列名若有误会静默失败）。
                await db.commit()
                print(f"  ✓ user_id={user_id} quota reset")

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