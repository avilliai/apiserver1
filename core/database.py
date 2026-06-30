"""
core/database.py — SQLAlchemy async setup + all core models
"""
import json
import asyncio
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase
from sqlalchemy import Column, Integer, String, DateTime, Boolean, Text, ForeignKey
from sqlalchemy.orm import relationship

DATABASE_URL = "sqlite+aiosqlite:///./gateway.db"

engine = create_async_engine(DATABASE_URL, echo=False)
AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

class Base(DeclarativeBase):
    pass

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(64), unique=True, index=True, nullable=False)
    hashed_password = Column(String(128), nullable=False)
    is_admin = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Quota stored as JSON string: {"openai_proxy": {"used": 5, "limit": 100}, ...}
    # limit=None means unlimited
    quota_json = Column(Text, default="{}")

    # 封禁状态（这些列在 gateway.db 中已存在，此处仅向 ORM 声明，无需迁移）
    is_banned = Column(Boolean, default=False, nullable=False)
    banned_at = Column(DateTime, nullable=True)
    ban_reason = Column(Text, nullable=True)

    @property
    def quota(self) -> dict:
        try:
            return json.loads(self.quota_json or "{}")
        except Exception:
            return {}

    @quota.setter
    def quota(self, value: dict):
        self.quota_json = json.dumps(value)

    logs = relationship("RequestLog", back_populates="user")
    api_keys = relationship("ApiKey", back_populates="user")

class ApiKey(Base):
    """
    Per-user API keys. Stored hashed; the raw key is only returned once at creation.
    Format: sk-<32 random hex chars>
    Auth flow: Authorization: Bearer sk-xxxx  →  look up by prefix, verify hash
    """
    __tablename__ = "api_keys"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    name = Column(String(128), nullable=False, default="Default Key")
    # First 10 chars of the raw key stored in plain text for display ("sk-a1b2c3...")
    key_prefix = Column(String(16), nullable=False, index=True)
    # SHA-256 hash of the full key
    key_hash = Column(String(64), nullable=False, unique=True, index=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    last_used_at = Column(DateTime, nullable=True)

    user = relationship("User", back_populates="api_keys")

class InviteCode(Base):
    __tablename__ = "invite_codes"

    id = Column(Integer, primary_key=True)
    code = Column(String(64), unique=True, index=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    created_by = Column(String(64), default="admin")

class RequestLog(Base):
    __tablename__ = "request_logs"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    plugin = Column(String(64), index=True)
    endpoint = Column(String(256))
    status_code = Column(Integer)
    created_at = Column(DateTime, default=datetime.utcnow)
    extra_json = Column(Text, default="{}")  # plugin-specific metadata

    user = relationship("User", back_populates="logs")

class AccessLog(Base):
    """
    中间件级别的请求审计日志（独立于 RequestLog，不影响现有统计/用量页）。

    由 core/access_log.py 的 ASGI 中间件为每个网关 API 调用写入一行：
    谁（user_id/username/api_key_prefix）、从哪（ip_address）、调了什么
    （method/plugin/endpoint）、参数（request_body）、返回了什么（response_body）。

    body 以可读 UTF-8 文本存储（非 \\uXXXX 转义），并在中间件层做体积上限与
    二进制占位处理，避免日志爆量。
    """
    __tablename__ = "access_logs"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    username = Column(String(64), index=True)        # 快照：匿名/失配时仍可读
    ip_address = Column(String(64), index=True)
    method = Column(String(8))
    plugin = Column(String(64), index=True)
    endpoint = Column(String(256), index=True)
    status_code = Column(Integer)
    request_body = Column(Text)                       # 可读文本，已截断/脱二进制
    response_body = Column(Text)
    api_key_prefix = Column(String(16))
    duration_ms = Column(Integer)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)


class BannedIp(Base):
    """
    被封禁的 IP（已存在的 banned_ips 表，此处向 ORM 声明）。
    管理员一键封禁时写入；core/access_log.py 启动时载入内存集做拦截。
    """
    __tablename__ = "banned_ips"

    id = Column(Integer, primary_key=True)
    ip_address = Column(String(64), index=True, nullable=False)
    user_id = Column(Integer, nullable=True)
    reason = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

async def get_db():
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()


# ── 应用层 Quota 写锁 ──────────────────────────────────────────────────────────
#
# 背景：SQLite + aiosqlite 不支持真正的行级锁（SELECT FOR UPDATE 被静默忽略）。
# 为了保证同一用户的 quota 读-改-写操作串行化，改用 asyncio.Lock。
#
# _user_quota_locks : user_id → asyncio.Lock
#   每个用户拥有独立的锁，用户之间互不影响。
#
# _quota_locks_guard : 保护 _user_quota_locks 字典本身的并发写入。
#   asyncio 是单线程事件循环，理论上字典操作本身不会有数据竞争，
#   但显式加锁使语义更清晰，且在引入多线程执行器时也能正确工作。
#
# 使用方法（在 require_quota 和 reset_all_quotas 中）：
#   lock = await get_user_quota_lock(user_id)
#   async with lock:
#       db.expire_all()           # 使 Session 缓存失效，确保读到数据库最新值
#       ...                       # 读 → 判断 → 改 → commit
#
_user_quota_locks: dict[int, asyncio.Lock] = {}
_quota_locks_guard = asyncio.Lock()


async def get_user_quota_lock(user_id: int) -> asyncio.Lock:
    """
    返回指定用户的 quota 写锁（懒初始化）。
    该锁在整个进程生命周期内复用，由 _quota_locks_guard 保护初始化过程。
    """
    async with _quota_locks_guard:
        if user_id not in _user_quota_locks:
            _user_quota_locks[user_id] = asyncio.Lock()
        return _user_quota_locks[user_id]