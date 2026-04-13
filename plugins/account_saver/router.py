"""
plugins/account_saver/router.py
"""

import json
from datetime import datetime
import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db, User
from core.quota import get_current_user, require_quota, log_request
from plugins.account_saver import config
import logging
logger = logging.getLogger(__name__)

PLUGIN_PREFIX = ""
PLUGIN_NAME = "account_saver"
router = APIRouter()

# ==================== 配置 ====================
TOKEN_MANAGER_URL = config.TOKEN_MANAGER_URL
TOKEN_MANAGER_KEY = config.TOKEN_MANAGER_KEY


# ==================== 工具函数 ====================

async def forward_to_token_manager(accounts: list[dict]) -> dict:
    # 直接传完整对象列表，TokenItem 需要 email/password/token
    payload = [
        {
            "email":    acc["email"],
            "password": acc["password"],
            "token":    acc.get("token", ""),
        }
        for acc in accounts
    ]

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            TOKEN_MANAGER_URL,
            json={"tokens": payload},   # ✅ list[TokenItem]，不是 list[str]
            headers={"Authorization": f"Bearer {TOKEN_MANAGER_KEY}"},
            timeout=30.0,
        )

    if resp.status_code != 200:
        raise HTTPException(
            status_code=502,
            detail=f"Token 管理器返回 {resp.status_code}: {resp.text}",
        )

    return resp.json()

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
            return {"status": "failed", "saved": 0}

        for acc in accounts:
            if not all(k in acc for k in ["email", "password", "token"]):
                raise HTTPException(status_code=400, detail="字段必须包含 email/password/token")

        tm_result = await forward_to_token_manager(accounts)

        await log_request(
            db, user, PLUGIN_NAME, "/save_accounts", 200,
            {"count": len(accounts)},
        )

        return {
            "status":        "success",
            "saved":         len(accounts),
            "token_manager": tm_result,
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
        "time": datetime.now().isoformat(),
    }