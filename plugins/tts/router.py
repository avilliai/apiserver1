"""
plugins/ai_translate/router.py

AI translation plugin supporting zh↔en and zh↔jp.
Calls the local OpenAI-compatible proxy internally.
"""
import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db, User
from core.quota import get_current_user, require_quota, log_request

import logging

from plugins.tts.HololiveTTS import HoliveTTS

logger = logging.getLogger(__name__)

PLUGIN_PREFIX = ""
PLUGIN_NAME = "文本转语音"
router = APIRouter()



tts1=HoliveTTS()



@router.post("/tts")
async def tts(
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _quota=Depends(require_quota(PLUGIN_NAME)),
):

    body = await request.json()
    text: str = body.get("text", "")
    lang: str = body.get("lang", "JP")
    speaker = body.get("speaker", "AZKI")

    if not text:
        raise HTTPException(
            status_code=400,
            detail=f"缺少 text 字段",
        )
    await log_request(db, user, PLUGIN_NAME, "/tts", 200, {})

    path=await tts1.synthesize(
            text=text,
            speaker=speaker,
            language=lang,
        )

    return {"url": path}
