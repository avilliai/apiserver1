"""
plugins/openai_proxy_v2/router.py

Proxies OpenAI-compatible requests to localhost:8007/v1 (v2 endpoint).
Supports both streaming and non-streaming responses.
Enforces per-user daily quota via core.quota.require_quota.
All models use the provider/model-name format (e.g. "anthropic/claude-sonnet-4.6").
"""
import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db, User
from core.quota import get_current_user, require_quota, log_request
from plugins.openai_proxy_v2 import config
import logging

logger = logging.getLogger(__name__)

PLUGIN_PREFIX = "/v2"
PLUGIN_NAME = "openai_proxy_v2"

router = APIRouter()


async def _proxy_request(
    path: str,
    body: dict,
    user: User,
    db: AsyncSession,
):
    model = body.get("model", "")
    if not model:
        raise HTTPException(status_code=400, detail="'model' field is required")

    # Upstream path always maps to /v1/...
    upstream_url = f"{config.UPSTREAM_BASE}/v1{path}"
    is_stream = body.get("stream", False)

    headers = {
        "Authorization": f"Bearer {config.UPSTREAM_API_KEY}",
        "Content-Type": "application/json",
    }

    logger.info(f"[v2] Proxying model='{model}' -> {upstream_url} (stream={is_stream})")

    if is_stream:
        async def generate():
            async with httpx.AsyncClient(timeout=120.0) as client:
                try:
                    async with client.stream(
                        "POST", upstream_url, json=body, headers=headers
                    ) as resp:
                        logger.info(f"[v2][STREAM] upstream status={resp.status_code}")
                        async for line in resp.aiter_lines():
                            if not line:
                                continue
                            yield f"{line.strip()}\n\n"
                except Exception as e:
                    logger.error(f"[v2][STREAM ERROR] {e}")
                    raise

        return StreamingResponse(generate(), media_type="text/event-stream")

    else:
        async with httpx.AsyncClient(timeout=120.0) as client:
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

@router.post("/v2/chat/completions")
async def chat_completions(
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _quota=Depends(require_quota(PLUGIN_NAME)),
):
    body = await request.json()
    return await _proxy_request("/chat/completions", body, user, db)


@router.post("/v2/completions")
async def completions(
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _quota=Depends(require_quota(PLUGIN_NAME)),
):
    body = await request.json()
    return await _proxy_request("/completions", body, user, db)


@router.post("/v2/embeddings")
async def embeddings(
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _quota=Depends(require_quota(PLUGIN_NAME)),
):
    body = await request.json()
    return await _proxy_request("/embeddings", body, user, db)


@router.get("/v2/models")
async def list_models(user: User = Depends(get_current_user)):
    """
    Fetches the live model list from the upstream and returns it as-is.
    Falls back to the static SUPPORTED_MODELS list if upstream is unavailable.
    """
    upstream_models_url = f"{config.UPSTREAM_BASE}/v1/models"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                upstream_models_url,
                headers={"Authorization": f"Bearer {config.UPSTREAM_API_KEY}"},
            )
        if resp.status_code == 200:
            return resp.json()
    except Exception as e:
        logger.warning(f"[v2] Failed to fetch upstream models: {e}, falling back to static list")

    # Static fallback
    return {
        "object": "list",
        "data": [
            {"id": model_id, "object": "model"}
            for model_id in config.SUPPORTED_MODELS
        ],
    }