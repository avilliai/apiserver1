"""
core/database.py — SQLAlchemy async setup + all core models
"""
import json
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

async def get_db():
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()