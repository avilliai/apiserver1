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
logger = logging.getLogger(__name__)

PLUGIN_PREFIX = ""
PLUGIN_NAME = "ai翻译"
router = APIRouter()

# 复用 openai_proxy 的上游地址和 key
from plugins.openai_proxy import config as openai_config
from plugins.openai_proxy.router import resolve_upstream

TRANSLATE_MODEL = "gpt-4o-mini"
INTERNAL_UPSTREAM = resolve_upstream(TRANSLATE_MODEL)
INTERNAL_URL = f"{INTERNAL_UPSTREAM}/v1/chat/completions"

# ── 支持的翻译方向 ────────────────────────────────────────────────

DIRECTION_PROMPTS: dict[str, str] = {
    "zh2en": (
        "You are a professional translator. "
        "Translate the following Chinese text into natural, fluent English. "
        "Output only the translated text, no explanations, no greetings, nothing else."
    ),
    "en2zh": (
        "你是一名专业翻译。"
        "将以下英文文本翻译成自然、流畅的中文。"
        "只输出译文，不要解释，不要寒暄，不要输出任何其他内容。"
    ),
    "zh2ja": (
        "あなたはプロの翻訳者です。"
        "以下の中国語テキストを自然で流暢な日本語に翻訳してください。"
        "翻訳結果のみを出力し、説明や挨拶など他の内容は一切出力しないでください。"
    ),
    "ja2zh": (
        "你是一名专业翻译。"
        "将以下日文文本翻译成自然、流畅的中文。"
        "只输出译文，不要解释，不要寒暄，不要输出任何其他内容。"
    ),
}

SUPPORTED_DIRECTIONS = list(DIRECTION_PROMPTS.keys())


# ── 核心翻译逻辑 ─────────────────────────────────────────────────

async def _do_translate(text: str, direction: str) -> str:
    if direction not in DIRECTION_PROMPTS:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的翻译方向: {direction}，可选: {SUPPORTED_DIRECTIONS}",
        )
    if not text or not text.strip():
        raise HTTPException(status_code=400, detail="text 不能为空")

    system_prompt = DIRECTION_PROMPTS[direction]
    payload = {
        "model": TRANSLATE_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": text.strip()},
        ],
        "temperature": 0.3,
        "stream": False,
    }
    headers = {
        "Authorization": f"Bearer {openai_config.UPSTREAM_API_KEY}",
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(INTERNAL_URL, json=payload, headers=headers)

    if resp.status_code >= 400:
        logger.error(f"[ai_translate] upstream error {resp.status_code}: {resp.text}")
        raise HTTPException(status_code=resp.status_code, detail=resp.text)

    data = resp.json()
    try:
        return data["choices"][0]["message"]["content"].strip()
    except (KeyError, IndexError) as e:
        logger.error(f"[ai_translate] unexpected response: {data}")
        raise HTTPException(status_code=502, detail=f"上游响应解析失败: {e}")


# ── 路由 ─────────────────────────────────────────────────────────

@router.post("/translate")
async def translate(
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _quota=Depends(require_quota(PLUGIN_NAME)),
):
    """
    请求体:
        {
            "text": "需要翻译的内容",
            "direction": "zh2en" | "en2zh" | "zh2ja" | "ja2zh"
        }

    响应:
        {
            "direction": "zh2en",
            "original": "...",
            "translation": "..."
        }
    """
    body = await request.json()
    text: str = body.get("text", "")
    direction: str = body.get("direction", "")

    if not direction:
        raise HTTPException(
            status_code=400,
            detail=f"缺少 direction 字段，可选: {SUPPORTED_DIRECTIONS}",
        )

    translation = await _do_translate(text, direction)

    await log_request(db, user, PLUGIN_NAME, "/translate", 200, {
        "direction": direction,
        "input_chars": len(text),
        "output_chars": len(translation),
    })

    return {
        "direction": direction,
        "original": text,
        "translation": translation,
    }


@router.get("/translate/directions")
async def list_directions(user: User = Depends(get_current_user)):
    """返回所有支持的翻译方向。"""
    return {"supported_directions": SUPPORTED_DIRECTIONS}