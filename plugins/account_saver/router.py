"""
plugins/account_saver/router.py
"""

import os
import asyncio
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db, User
from core.quota import get_current_user, require_quota, log_request
import logging
logger = logging.getLogger(__name__)

PLUGIN_PREFIX = ""
PLUGIN_NAME = "account_saver"
router = APIRouter()

# ==================== 配置 ====================
SAVE_DIR = os.path.dirname(os.path.abspath(__file__))
SERVER_ACCOUNTS_FILE = os.path.join(SAVE_DIR, "server_accounts.txt")
SERVER_TOKENS_FILE = os.path.join(SAVE_DIR, "server_tokens.txt")

# asyncio 锁（替代 threading.Lock）
_SAVE_LOCK = asyncio.Lock()


# ==================== 工具函数 ====================

async def save_batch_to_files(accounts):
    async with _SAVE_LOCK:
        # 写完整信息
        with open(SERVER_ACCOUNTS_FILE, "a", encoding="utf-8") as f:
            for acc in accounts:
                f.write(f"{acc['email']} | {acc['password']} | {acc['token']}\n")

        # 写 token
        with open(SERVER_TOKENS_FILE, "a", encoding="utf-8") as f:
            for acc in accounts:
                f.write(f"{acc['token']}\n")

    logger.info(f" 💾 保存 {len(accounts)} 个账号")


# ==================== API ====================

@router.post("/save_accounts")
async def save_accounts(
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _quota=Depends(require_quota(PLUGIN_NAME)),
):
    try:
        data = await request.json()

        if not data or not isinstance(data.get("accounts"), list):
            raise HTTPException(status_code=400, detail="必须包含 accounts 列表")

        accounts = data["accounts"]

        if not accounts:
            await log_request(db, user, PLUGIN_NAME, "/save_accounts", 200)
            return {"status": "success", "saved": 0}

        # 校验字段
        for acc in accounts:
            if not all(k in acc for k in ["email", "password", "token"]):
                raise HTTPException(status_code=400, detail="字段必须包含 email/password/token")

        await save_batch_to_files(accounts)

        await log_request(
            db,
            user,
            PLUGIN_NAME,
            "/save_accounts",
            200,
            {"count": len(accounts)}
        )

        return {
            "status": "success",
            "saved": len(accounts),
            "message": f"已保存 {len(accounts)} 个账号"
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[ERROR] {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/health")
async def health():
    return {
        "status": "ok",
        "time": datetime.now().isoformat()
    }