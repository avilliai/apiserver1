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

# ── 内部工具 ────────────────────────────────────────────────────

SUPPORTED_LANGS = {"zh", "en", "ja", "jp", "all_zh", "all_ja", "all_yue",
                   "zh_mix_en", "yue_mix_en", "auto", "auto_yue"}


async def _call_gptsovits(text: str, text_lang: str) -> bytes:
    """
    向 GPT-SoVITS 发送 GET /tts 请求，返回 WAV 字节。
    ref_audio_path / prompt_text / prompt_lang 固定在 config 里。
    """
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
        # GPT-SoVITS 失败时返回 JSON
        try:
            detail = resp.json()
        except Exception:
            detail = resp.text
        raise HTTPException(status_code=resp.status_code, detail=detail)

    return resp.content   # WAV 二进制


# ── 路由 ────────────────────────────────────────────────────────

@router.get("/tts")
async def gptsovits_tts(
    request:  Request,
    user:     User         = Depends(get_current_user),
    db:       AsyncSession = Depends(get_db),
    _quota                 = Depends(require_quota(PLUGIN_NAME)),
):
    """
    GET /gptsovits/tts?text=...&text_lang=zh

    参数：
      text      (必填) 要合成的文本
      text_lang (可选) 语言，默认 zh；支持 zh / en / ja / auto 等
    返回：
      audio/wav 二进制流
    """
    params    = request.query_params
    text      = params.get("text", "").strip()
    text_lang = params.get("text_lang", "zh").strip().lower()

    if not text:
        raise HTTPException(status_code=400, detail="缺少 text 参数")

    if text_lang not in SUPPORTED_LANGS:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的语言: {text_lang}，可选: {sorted(SUPPORTED_LANGS)}",
        )

    logger.info("gptsovits tts | user=%s lang=%s len=%d", user.id, text_lang, len(text))

    audio_bytes = await _call_gptsovits(text, text_lang)

    await log_request(db, user, PLUGIN_NAME, "/tts", 200, {})

    return Response(
        content      = audio_bytes,
        media_type   = "audio/wav",
        headers      = {"Content-Disposition": "inline; filename=output.wav"},
    )


@router.post("/tts")
async def gptsovits_tts_post(
    request:  Request,
    user:     User         = Depends(get_current_user),
    db:       AsyncSession = Depends(get_db),
    _quota                 = Depends(require_quota(PLUGIN_NAME)),
):
    """
    POST /gptsovits/tts
    Body (JSON)：{ "text": "...", "text_lang": "zh" }

    与 GET 版本等价，方便需要发 JSON 的客户端。
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

    logger.info("gptsovits tts POST | user=%s lang=%s len=%d", user.id, text_lang, len(text))

    audio_bytes = await _call_gptsovits(text, text_lang)

    await log_request(db, user, PLUGIN_NAME, "/tts", 200, {})

    return Response(
        content    = audio_bytes,
        media_type = "audio/wav",
        headers    = {"Content-Disposition": "inline; filename=output.wav"},
    )