"""
plugins/gptsovits/router.py

GPT-SoVITS TTS 插件。
向本地 GPT-SoVITS 服务（localhost:3529）发 GET 请求，
把返回的 WAV 音频流直接透传给客户端。
"""
import logging

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db, User
from core.quota import get_current_user, require_quota, log_request
from plugins.gpt_sovits import config

logger = logging.getLogger(__name__)

PLUGIN_PREFIX = "/gptsovits"
PLUGIN_NAME   = "gptsovits"

router = APIRouter()

SUPPORTED_LANGS = {
    "zh", "en", "ja", "jp",
    "all_zh", "all_ja", "all_yue",
    "zh_mix_en", "yue_mix_en",
    "auto", "auto_yue",
}


async def _call_gptsovits(text: str, text_lang: str) -> bytes:
    """向 GPT-SoVITS 发 GET /tts，返回 WAV 字节。"""
    params = {
        "text":           text,
        "text_lang":      text_lang,
        "ref_audio_path": config.REF_AUDIO_PATH,
        "prompt_text":    config.PROMPT_TEXT,
        "prompt_lang":    config.PROMPT_LANG,
        "media_type":     "wav",
        "streaming_mode": False,
    }

    async with httpx.AsyncClient(timeout=120.0) as client:
        resp = await client.get(f"{config.BACKEND_BASE}/tts", params=params)

    if resp.status_code != 200:
        try:
            detail = resp.json()
        except Exception:
            detail = resp.text
        raise HTTPException(status_code=resp.status_code, detail=detail)

    return resp.content


# ── POST（主要入口）─────────────────────────────────────────────

@router.post("/tts")
async def gptsovits_tts(
    request: Request,
    user:    User         = Depends(get_current_user),
    db:      AsyncSession = Depends(get_db),
    _quota               = Depends(require_quota(PLUGIN_NAME)),
):
    """
    POST /gptsovits/tts
    Body JSON：{ "text": "...", "text_lang": "zh" }
    返回：audio/wav 二进制流
    """
    body      = await request.json()
    text      = body.get("text", "").strip()
    text_lang = body.get("text_lang", "zh").strip().lower()

    if not text:
        raise HTTPException(status_code=400, detail="缺少 text 字段")

    if text_lang not in SUPPORTED_LANGS:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的语言: {text_lang}，可选: {sorted(SUPPORTED_LANGS)}",
        )

    logger.info("gptsovits tts | user=%s lang=%s len=%d", user.id, text_lang, len(text))

    audio_bytes = await _call_gptsovits(text, text_lang)

    await log_request(db, user, PLUGIN_NAME, "/tts", 200, {})

    return Response(
        content    = audio_bytes,
        media_type = "audio/wav",
        headers    = {"Content-Disposition": "inline; filename=output.wav"},
    )