"""
plugins/gptsovits/router.py

GPT-SoVITS TTS 插件。
向本地 GPT-SoVITS 服务（localhost:3529）发 POST 请求，
把返回的 WAV 音频流直接透传给客户端。

客户端只需传 text / text_lang 即可，其余推理参数（ref_audio_path、
prompt_text、top_k 等）使用 config.TTS_DEFAULTS 自动补全；
客户端若传入同名字段，则覆盖网关默认值后再转发给真实服务端。
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
PLUGIN_NAME   = "gpt_sovits"

router = APIRouter()

SUPPORTED_LANGS = {
    "zh", "en", "ja", "jp",
    "all_zh", "all_ja", "all_yue",
    "zh_mix_en", "yue_mix_en",
    "auto", "auto_yue",
}


async def _call_gptsovits(text: str, text_lang: str, overrides: dict) -> bytes:
    """
    向 GPT-SoVITS 真实服务端发 POST /tts，返回 WAV 字节。

    参数补全规则：
      - text / text_lang 由调用方传入（必填，已校验）。
      - 其余字段先用 config.TTS_DEFAULTS 补全，再用客户端请求体里
        同名且在 TTS_OVERRIDABLE_FIELDS 白名单内的字段覆盖默认值。
    """
    payload = {
        "text":      text,
        "text_lang": text_lang,
        **config.TTS_DEFAULTS,
    }
    for key, value in overrides.items():
        if key in config.TTS_OVERRIDABLE_FIELDS:
            payload[key] = value

    async with httpx.AsyncClient(timeout=120.0) as client:
        resp = await client.post(f"{config.BACKEND_BASE}/tts", json=payload)

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
    Body JSON: { "text": "...", "text_lang": "zh", ... }

    text / text_lang 必填，其余推理参数（ref_audio_path、prompt_text、
    top_k、speed_factor 等，见 config.TTS_DEFAULTS）均为可选：
    不传则使用网关 config 中的默认值自动补全；传了则覆盖默认值。

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

    # text / text_lang 已单独处理，剩余字段作为可覆盖的推理参数传给真实服务端
    overrides = {k: v for k, v in body.items() if k not in ("text", "text_lang")}

    logger.info(
        "gptsovits tts | user=%s lang=%s len=%d overrides=%s",
        user.id, text_lang, len(text), list(overrides.keys()),
    )

    audio_bytes = await _call_gptsovits(text, text_lang, overrides)

    await log_request(db, user, PLUGIN_NAME, "/tts", 200, {})

    return Response(
        content    = audio_bytes,
        media_type = "audio/wav",
        headers    = {"Content-Disposition": "inline; filename=output.wav"},
    )