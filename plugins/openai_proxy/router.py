"""
plugins/openai_proxy/router.py

Proxies OpenAI-compatible requests to different upstreams based on model name.
Supports both streaming and non-streaming responses.
Enforces per-user quota via core.quota.require_quota.
"""
import json
import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db, User
from core.quota import get_current_user, require_quota, log_request
from plugins.openai_proxy import config
import logging

logger = logging.getLogger("ai_proxy")
# Prefix this plugins mounts at
PLUGIN_PREFIX = ""

router = APIRouter()

PLUGIN_NAME = "openai_proxy"


def resolve_upstream(model: str) -> str:
    """Match model name prefix to an upstream base URL."""
    model_lower = model.lower()
    for prefix, url in config.UPSTREAM_ROUTES.items():
        if model_lower.startswith(prefix):
            return url
    # Default fallback
    return list(config.UPSTREAM_ROUTES.values())[-1]


async def _proxy_request(
    path: str,
    body: dict,
    user: User,
    db: AsyncSession,
):
    model = body.get("model", "")
    if not model:
        raise HTTPException(status_code=400, detail="'model' field is required")

    upstream_base = resolve_upstream(model)
    upstream_url = f"{upstream_base}{path}"
    is_stream = body.get("stream", False)

    headers = {
        "Authorization": f"Bearer {config.UPSTREAM_API_KEY}",
        "Content-Type": "application/json",
    }
    logger.info(f"Proxying request for model '{model}' to {upstream_url} (stream={is_stream})")
    async with httpx.AsyncClient(timeout=120.0) as client:
        if is_stream:
            async def generate():
                #print("🔥 [STREAM] start")

                async with httpx.AsyncClient(timeout=120.0) as client:
                    try:
                        async with client.stream(
                                "POST", upstream_url, json=body, headers=headers
                        ) as resp:
                            #print(f"🔥 [UPSTREAM STATUS] {resp.status_code}")
                            logger.info(f"🔥 [UPSTREAM HEADERS] {resp.headers}")

                            async for line in resp.aiter_lines():
                                #print(f"🔥 [RAW LINE] {repr(line)}")  # 👈 核心

                                if not line:
                                    continue

                                data = line.strip()

                                #print(f"🔥 [YIELD] {data}")  # 👈 看你到底有没有发出去

                                yield f"{data}\n\n"

                    except Exception as e:
                        logger.error("❌ [STREAM ERROR]", e)
                        raise

            return StreamingResponse(generate(), media_type="text/event-stream")

        else:
            resp = await client.post(upstream_url, json=body, headers=headers)
            try:
                resp_json = resp.json()
            except Exception:
                resp_json = {"error": resp.text}

            usage = resp_json.get("usage", {}) if isinstance(resp_json, dict) else {}
            await log_request(db, user, PLUGIN_NAME, path, resp.status_code, {
                "model": model,
                "prompt_tokens": usage.get("prompt_tokens", 0),
                "completion_tokens": usage.get("completion_tokens", 0),
                "stream": False,
            })

            if resp.status_code >= 400:
                raise HTTPException(status_code=resp.status_code, detail=resp_json)

            return resp_json


# ---------- Endpoints ----------

@router.post("/v1/chat/completions")
async def chat_completions(
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _quota=Depends(require_quota(PLUGIN_NAME)),
):
    body = await request.json()
    return await _proxy_request("/v1/chat/completions", body, user, db)


@router.post("/v1/completions")
async def completions(
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _quota=Depends(require_quota(PLUGIN_NAME)),
):
    body = await request.json()
    return await _proxy_request("/v1/completions", body, user, db)


@router.post("/v1/embeddings")
async def embeddings(
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _quota=Depends(require_quota(PLUGIN_NAME)),
):
    body = await request.json()
    return await _proxy_request("/v1/embeddings", body, user, db)


@router.get("/v1/models")
async def list_models(user: User = Depends(get_current_user)):
    """Returns supported model families based on config."""
    return {
        "object": "list",
        "data": [
            {"id": prefix, "object": "model", "upstream": url}
            for prefix, url in config.UPSTREAM_ROUTES.items()
        ],
    }
