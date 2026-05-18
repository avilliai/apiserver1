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
- 特殊 V2 -> V1 模型映射：提供短名称供调用并扣除 v1 配额，长名称保留 v2 属性。
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

# ================= 核心修改：特殊 v2 短名称映射 =================
# 当用户请求短名称时，将其转往 v2 上游但扣除 v1 配额。
# 用户请求长名称时不受影响，正常扣除 v2 配额。
SPECIAL_V2_TO_V1_MODELS = {
    "qwen3.6-27b": "alibaba/qwen3.6-27b",
    "qwen3.6-35b-a3b": "alibaba/qwen3.6-35b-a3b",
    "qwen3.6-flash": "alibaba/qwen3.6-flash",
    "gpt-oss-120b": "openai/gpt-oss-120b",
    "mistral-small-4-119b": "mistral/mistral-small-4-119b",
    "glm-4.7-flash": "zai/glm-4.7-flash",
    "deepseek-v4-flash": "deepseek/deepseek-v4-flash",
    "trinity-large-thinking": "arcee/trinity-large-thinking",
    "nemotron-3-super-120b-a12b": "nvidia/nemotron-3-super-120b-a12b",
    "mimo-v2-flash": "xiaomi/mimo-v2-flash",
    "step-3.5-flash": "stepfun/step-3.5-flash",
}
# ==========================================================

router = APIRouter()


def _resolve(model: str) -> tuple[str, str, str]:
    """
    返回 (upstream_base_url, api_key, plugin_name)。

    优先级：
      1. Pegasus/ 前缀 → v3 上游 (localhost:8011)
      2. 特殊 v2 短名称映射 → v2 上游，但使用 v1 插件配额
      3. v2 精确匹配 (含长名称) → v2 上游
      4. v1 前缀路由表 → v1 上游
      5. fallback      → v1 最后一个上游
    """
    model_lower = model.lower()

    # ── 1. v3：Pegasus/ 前缀判断 ──────────────────────────────────────────────
    if model in _V3_MODELS or model.startswith(v3_config.MODEL_PREFIX):
        return v3_config.UPSTREAM_BASE, v3_config.UPSTREAM_API_KEY, V3_PLUGIN_NAME

    # ── 2. v2 -> v1 特殊短名称（仅短名称走 v1 计费）─────────────────────────
    if model_lower in SPECIAL_V2_TO_V1_MODELS:
        return v2_config.UPSTREAM_BASE, v2_config.UPSTREAM_API_KEY, PLUGIN_NAME

    # ── 3. v2：精确匹配 (长名称如 alibaba/qwen3.6-flash 走此处，正常 v2 计费) ──
    if model_lower in _V2_MODELS:
        return v2_config.UPSTREAM_BASE, v2_config.UPSTREAM_API_KEY, V2_PLUGIN_NAME

    # ── 4. v1：前缀路由 ────────────────────────────────────────────────────────
    for prefix, url in config.UPSTREAM_ROUTES.items():
        if model_lower.startswith(prefix):
            return url, config.UPSTREAM_API_KEY, PLUGIN_NAME

    # 默认 fallback
    return list(config.UPSTREAM_ROUTES.values())[-1], config.UPSTREAM_API_KEY, PLUGIN_NAME


def _prepare_body(body: dict, effective_plugin: str) -> dict:
    """
    根据目标插件对请求体做必要的预处理。
    """
    model = body.get("model", "")
    model_lower = model.lower()

    # 处理 v3 剥离
    if effective_plugin == V3_PLUGIN_NAME:
        if model.startswith(v3_config.MODEL_PREFIX):
            return {**body, "model": model[len(v3_config.MODEL_PREFIX):]}

    # 处理特殊 v2 短名称 -> 长名称回填
    if effective_plugin == PLUGIN_NAME and model_lower in SPECIAL_V2_TO_V1_MODELS:
        return {**body, "model": SPECIAL_V2_TO_V1_MODELS[model_lower]}

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

    # 动态构建转发的请求体 (替换名字等预处理)
    upstream_body = _prepare_body(body, effective_plugin)

    # ── 动态配额检查 ──────────────────────────────────────────────────────────
    await require_quota(effective_plugin)(user=user, db=db)
    # ─────────────────────────────────────────────────────────────────────────

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    logger.info(
        f"Proxying '{model}' (effective target: '{upstream_body.get('model')}') -> {upstream_url} "
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
            "model": model,   # 日志保留用户原始请求的名（例如短名称），便于追溯
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
    获取模型列表并强制按照需求排版：
    原生 v1 -> 短名称特供(v1扣费) -> 原生 v2长名称 -> 原生 v3
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
                    for m in models:
                        if "id" in m and not m["id"].startswith(prefix):
                            m["id"] = prefix + m["id"]
                return models
        except Exception as e:
            logger.warning(f"Failed to fetch models from {base_url}: {e}")
        return []

    # 去重提取各上游任务
    unique_v1 = {url: config.UPSTREAM_API_KEY for url in config.UPSTREAM_ROUTES.values()}
    unique_v2 = {v2_config.UPSTREAM_BASE: v2_config.UPSTREAM_API_KEY}
    v3_upstream = (v3_config.UPSTREAM_BASE, v3_config.UPSTREAM_API_KEY, v3_config.MODEL_PREFIX)

    v1_tasks = [fetch_models(url, key) for url, key in unique_v1.items()]
    v2_tasks = [fetch_models(url, key) for url, key in unique_v2.items()]
    v3_tasks = [fetch_models(v3_upstream[0], v3_upstream[1], v3_upstream[2])]

    # 并发请求全部上游
    all_results = await asyncio.gather(*(v1_tasks + v2_tasks + v3_tasks))

    # 拆分结果用于有序合并
    v1_results = all_results[:len(v1_tasks)]
    v2_results = all_results[len(v1_tasks):len(v1_tasks)+len(v2_tasks)]
    v3_results = all_results[len(v1_tasks)+len(v2_tasks):]

    # 合并去重字典 (Python 3.7+ 字典保持插入顺序)
    merged: dict[str, dict] = {}

    # 1. 插入原生 V1 模型
    for models in v1_results:
        for m in models:
            if "id" in m:
                merged[m["id"]] = m

    # 提取 V2 原始列表，用于复制短名称的元数据
    v2_models_list = []
    for models in v2_results:
        v2_models_list.extend(models)
    v2_dict = {m["id"]: m for m in v2_models_list if "id" in m}

    # 2. 插入短名称伪装模型 (紧跟在 V1 后面)
    for short_name, long_name in SPECIAL_V2_TO_V1_MODELS.items():
        if long_name in v2_dict:
            special_m = v2_dict[long_name].copy()
            special_m["id"] = short_name
            merged[short_name] = special_m
        else:
            # Fallback 创建
            merged[short_name] = {
                "id": short_name,
                "object": "model",
                "created": 1700000000,
                "owned_by": "apollodorus"
            }

    # 3. 插入原生 V2 模型 (包含长名称)
    for m in v2_models_list:
        if "id" in m:
            merged[m["id"]] = m

    # 4. 插入 V3 模型
    for models in v3_results:
        for m in models:
            if "id" in m:
                merged[m["id"]] = m

    return {"object": "list", "data": list(merged.values())}