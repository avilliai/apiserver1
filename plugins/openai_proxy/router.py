"""
plugins/openai_proxy/router.py

Proxies OpenAI-compatible requests to different upstreams based on model name.
Supports both streaming and non-streaming responses.

配额逻辑：
- 普通模型（v1）：从 "openai_proxy" bucket 扣除，转发到 UPSTREAM_ROUTES
- V2 模型（config.V2_MODELS 精确匹配）：从 "openai_proxy_v2" bucket 扣除，
  转发到 V2_UPSTREAM_BASE，请求路径保持 /v1/...（上游接受标准 OpenAI 格式）
- V3 模型（Pegasus/ 前缀）：从 "openai_proxy_v3" bucket 扣除，
  转发到 localhost:8011，转发前剥离 "Pegasus/" 前缀

quota.py 未做任何修改，通过直接 await 调用 require_quota() 返回的内部
_check 函数实现运行时动态切换 plugin_name。
"""
import asyncio

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db, User
from core.quota import get_current_user, require_quota, log_request
from plugins.openai_proxy import config
from plugins.openai_proxy_v2 import config as v2_config
from plugins.openai_proxy_v3 import config as v3_config
import logging

logger = logging.getLogger(__name__)

PLUGIN_PREFIX = ""
PLUGIN_NAME = "openai_proxy"
V2_PLUGIN_NAME = "openai_proxy_v2"
V3_PLUGIN_NAME = "openai_proxy_v3"

_V2_MODELS: set[str] = set(v2_config.SUPPORTED_MODELS)
_V3_MODELS: set[str] = set(v3_config.SUPPORTED_MODELS)   # 均带 "Pegasus/" 前缀

router = APIRouter()


def _resolve(model: str) -> tuple[str, str, str]:
    """
    返回 (upstream_base_url, api_key, plugin_name)。

    优先级：
      1. Pegasus/ 前缀 → v3 上游 (localhost:8011)
      2. v2 精确匹配   → v2 上游
      3. v1 前缀路由表 → v1 上游
      4. fallback      → v1 最后一个上游
    """
    # ── v3：Pegasus/ 前缀判断 ────────────────────────────────────────────────
    if model in _V3_MODELS or model.startswith(v3_config.MODEL_PREFIX):
        return v3_config.UPSTREAM_BASE, v3_config.UPSTREAM_API_KEY, V3_PLUGIN_NAME

    # ── v2：精确匹配 ─────────────────────────────────────────────────────────
    if model.lower() in _V2_MODELS:
        return v2_config.UPSTREAM_BASE, v2_config.UPSTREAM_API_KEY, V2_PLUGIN_NAME

    # ── v1：前缀路由 ─────────────────────────────────────────────────────────
    model_lower = model.lower()
    for prefix, url in config.UPSTREAM_ROUTES.items():
        if model_lower.startswith(prefix):
            return url, config.UPSTREAM_API_KEY, PLUGIN_NAME

    # 默认 fallback
    return list(config.UPSTREAM_ROUTES.values())[-1], config.UPSTREAM_API_KEY, PLUGIN_NAME


def _prepare_body(body: dict, effective_plugin: str) -> dict:
    """
    根据目标插件对请求体做必要的预处理。
    v3：剥离模型名中的 "Pegasus/" 前缀，上游只认裸名。
    其他插件：原样返回。
    """
    if effective_plugin == V3_PLUGIN_NAME:
        model = body.get("model", "")
        if model.startswith(v3_config.MODEL_PREFIX):
            return {**body, "model": model[len(v3_config.MODEL_PREFIX):]}
    return body


async def _proxy_request(
    path: str,
    body: dict,
    user: User,
    db: AsyncSession,
):
    model = body.get("model", "")
    if not model:
        raise HTTPException(status_code=400, detail="'model' field is required")

    upstream_base, api_key, effective_plugin = _resolve(model)
    upstream_url = f"{upstream_base}{path}"
    is_stream = body.get("stream", False)

    # 对 v3 模型剥离前缀后再转发
    upstream_body = _prepare_body(body, effective_plugin)

    # ── 动态配额检查 ──────────────────────────────────────────────────────────
    await require_quota(effective_plugin)(user=user, db=db)
    # ─────────────────────────────────────────────────────────────────────────

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    logger.info(
        f"Proxying '{model}' -> {upstream_url} "
        f"(plugin={effective_plugin}, stream={is_stream})"
    )

    if is_stream:
        async def generate():
            async with httpx.AsyncClient(timeout=None) as client:
                try:
                    async with client.stream(
                        "POST", upstream_url, json=upstream_body, headers=headers
                    ) as resp:
                        logger.info(f"[UPSTREAM HEADERS] {resp.headers}")
                        async for line in resp.aiter_lines():
                            if not line:
                                continue
                            yield f"{line.strip()}\n\n"
                except Exception as e:
                    logger.error(f"[STREAM ERROR] {e}")
                    raise

        return StreamingResponse(generate(), media_type="text/event-stream")

    else:
        async with httpx.AsyncClient(timeout=None) as client:
            resp = await client.post(upstream_url, json=upstream_body, headers=headers)

        try:
            resp_json = resp.json()
        except Exception:
            resp_json = {"error": resp.text}

        usage = (resp_json.get("usage") or {}) if isinstance(resp_json, dict) else {}
        await log_request(db, user, effective_plugin, path, resp.status_code, {
            "model": model,   # 日志保留原始带前缀名，便于追溯
            "prompt_tokens": usage.get("prompt_tokens", 0),
            "completion_tokens": usage.get("completion_tokens", 0),
            "stream": False,
        })

        if resp.status_code >= 400:
            raise HTTPException(status_code=resp.status_code, detail=resp_json)

        return resp_json


# ---------- Endpoints ----------
# 注意：quota 检查已移入 _proxy_request，这里不再挂 _quota=Depends(require_quota(...))，
# 否则会对同一请求扣两次 v1 配额。

@router.post("/v1/chat/completions")
async def chat_completions(
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    body = await request.json()
    return await _proxy_request("/v1/chat/completions", body, user, db)


@router.post("/v1/completions")
async def completions(
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    body = await request.json()
    return await _proxy_request("/v1/completions", body, user, db)


@router.post("/v1/embeddings")
async def embeddings(
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    body = await request.json()
    return await _proxy_request("/v1/embeddings", body, user, db)


@router.get("/v1/models")
async def list_models(user: User = Depends(get_current_user)):
    """
    从所有上游（v1、v2、v3）并发拉取模型列表并合并去重。
    v3 模型在返回时恢复 Pegasus/ 前缀，与上游裸名区分。
    """

    async def fetch_models(base_url: str, api_key: str, prefix: str = "") -> list:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(
                    f"{base_url}/v1/models",
                    headers={"Authorization": f"Bearer {api_key}"},
                )
            if resp.status_code == 200:
                models = resp.json().get("data", [])
                if prefix:
                    # 为 v3 模型加上 Pegasus/ 前缀，避免与同名 v1 模型冲突
                    for m in models:
                        if "id" in m and not m["id"].startswith(prefix):
                            m["id"] = prefix + m["id"]
                return models
        except Exception as e:
            logger.warning(f"Failed to fetch models from {base_url}: {e}")
        return []

    # v1 各上游（去重 URL）
    unique_v1 = {url: config.UPSTREAM_API_KEY for url in config.UPSTREAM_ROUTES.values()}
    # v2 上游
    unique_v2 = {v2_config.UPSTREAM_BASE: v2_config.UPSTREAM_API_KEY}
    # v3 上游（需要加前缀）
    v3_upstream = (v3_config.UPSTREAM_BASE, v3_config.UPSTREAM_API_KEY, v3_config.MODEL_PREFIX)

    tasks = (
        [fetch_models(url, key) for url, key in unique_v1.items()] +
        [fetch_models(url, key) for url, key in unique_v2.items()] +
        [fetch_models(v3_upstream[0], v3_upstream[1], v3_upstream[2])]
    )

    results = await asyncio.gather(*tasks)

    # 合并去重，以 id 为唯一键
    merged: dict[str, dict] = {}
    for models in results:
        for m in models:
            if "id" in m:
                merged[m["id"]] = m

    return {"object": "list", "data": list(merged.values())}