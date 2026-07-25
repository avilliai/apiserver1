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
- Claude (Anthropic Messages API)：从 "openai_proxy" bucket 扣除（与 OpenAI 请求共用），
  转发到 config.CLAUDE_UPSTREAM_BASE 的 /v1/messages（即 arting2api 服务新增的 Anthropic 兼容端点）
"""
import asyncio
import hashlib

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db, User, ApiKey
from core.quota import get_current_user, require_quota, log_request
from core.auth_utils import decode_token
from plugins.openai_proxy_v0 import config

import logging

logger = logging.getLogger(__name__)

PLUGIN_PREFIX = ""
PLUGIN_NAME = "openai_proxy_v0"



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
    if model_lower not in ['openrouter:openai/gpt-5.4-nano','openrouter:openai/gpt-4o-mini','openrouter:deepseek/deepseek-v4-pro', 'openrouter:deepseek/deepseek-v4-flash', 'openrouter:deepseek/deepseek-v3.2']:
        logger.info(f"不允许的模型名{model_lower}，已替换为 openrouter:deepseek/deepseek-v4-flash")
        model_lower="openrouter:deepseek/deepseek-v4-flash"
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
                        # 原样透传字节流，不按行重新拼接 —— 按行拼接会把多行一组的 SSE 事件
                        # （例如 Anthropic 的 event: + data: 两行结构）拆坏。
                        async for chunk in resp.aiter_bytes():
                            yield chunk
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

@router.post("/v0/chat/completions")
async def chat_completions(
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    body = await request.json()
    return await _proxy_request("/v0/chat/completions", body, user, db)


@router.post("/v0/completions")
async def completions(
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    body = await request.json()
    return await _proxy_request("/v0/completions", body, user, db)


@router.post("/v0/embeddings")
async def embeddings(
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    body = await request.json()
    return await _proxy_request("/v0/embeddings", body, user, db)


@router.get("/v0/models")
async def list_models(user: User = Depends(get_current_user)):
    """
    获取模型列表并强制按照需求排版：
    原生 v1 -> 短名称特供(v1扣费) -> 原生 v2长名称 -> 原生 v3
    """

    async def fetch_models(base_url: str, api_key: str, prefix: str = "") -> list:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(
                    f"{base_url}/v0/models",
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


    v1_tasks = [fetch_models(url, key) for url, key in unique_v1.items()]


    # 并发请求全部上游
    all_results = await asyncio.gather(*(v1_tasks))

    # 拆分结果用于有序合并
    v1_results = all_results[:len(v1_tasks)]


    # 合并去重字典 (Python 3.7+ 字典保持插入顺序)
    merged: dict[str, dict] = {}

    # 1. 插入原生 V1 模型
    for models in v1_results:
        for m in models:
            if "id" in m:
                merged[m["id"]] = m


    return {"object": "list", "data": list(merged.values())}


# ==========================================================
# Claude (Anthropic Messages API) 兼容端点 —— 全新增，不影响以上任何逻辑
# ==========================================================

def _hash_key(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


async def get_current_user_claude(
    x_api_key: str | None = Header(default=None, alias="x-api-key"),
    authorization: str | None = Header(default=None),
    db: AsyncSession = Depends(get_db),
) -> User:
    """
    Claude Code CLI 默认用 `x-api-key` 传凭证，不是 `Authorization: Bearer`。
    这里复刻 core/quota.py::get_current_user 的两条鉴权路径
    （sk- API Key 查库 / JWT），只是凭证来源换成 x-api-key
    （同时兼容 Authorization: Bearer，防止个别客户端习惯不同）。
    不修改 core/quota.py 本身，用户的 sk- API Key 在两条路径下通用。
    """
    token = x_api_key or (authorization.removeprefix("Bearer ").strip() if authorization else None)
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated. Set x-api-key header.")

    # ── Path 1: API Key (starts with "sk-") ──────────────────────────────────
    if token.startswith("sk-"):
        key_hash = _hash_key(token)
        result = await db.execute(
            select(ApiKey).where(ApiKey.key_hash == key_hash, ApiKey.is_active == True)
        )
        api_key = result.scalar_one_or_none()
        if not api_key:
            raise HTTPException(status_code=401, detail="Invalid or revoked API key")

        user_result = await db.execute(select(User).where(User.id == api_key.user_id))
        user = user_result.scalar_one_or_none()
        if not user:
            raise HTTPException(status_code=401, detail="User not found")
        return user

    # ── Path 2: JWT Bearer token ──────────────────────────────────────────────
    payload = decode_token(token)
    user_id = int(payload.get("sub", 0))
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return user


@router.post("/v0/messages")
async def anthropic_messages(
    request: Request,
    user: User = Depends(get_current_user_claude),
    db: AsyncSession = Depends(get_db),
):
    body = await request.json()
    model = body.get("model", "unknown")
    is_stream = bool(body.get("stream", False))

    # 与 OpenAI 请求共用同一个 "openai_proxy" 配额 bucket。
    # 如果想让 Claude Code 走独立配额，告诉我一声，加一个新的
    # plugins/openai_proxy_claude/config.py 就够了，不需要新建整个插件。
    await require_quota(PLUGIN_NAME)(user=user, db=db)

    upstream_url = f"{config.CLAUDE_UPSTREAM_BASE}/v0/messages"
    headers = {
        "x-api-key": config.CLAUDE_UPSTREAM_API_KEY,
        "content-type": "application/json",
        "anthropic-version": request.headers.get("anthropic-version", "2023-06-01"),
    }

    logger.info(f"Proxying Claude '{model}' -> {upstream_url} (stream={is_stream})")

    if is_stream:
        async def generate():
            async with httpx.AsyncClient(timeout=None) as client:
                try:
                    async with client.stream(
                        "POST", upstream_url, json=body, headers=headers
                    ) as resp:
                        async for chunk in resp.aiter_bytes():
                            yield chunk
                except Exception as e:
                    logger.error(f"[CLAUDE STREAM ERROR] {e}")
                    raise

        return StreamingResponse(generate(), media_type="text/event-stream")

    async with httpx.AsyncClient(timeout=None) as client:
        resp = await client.post(upstream_url, json=body, headers=headers)

    try:
        resp_json = resp.json()
    except Exception:
        resp_json = {"error": resp.text}

    usage = (resp_json.get("usage") or {}) if isinstance(resp_json, dict) else {}
    await log_request(db, user, PLUGIN_NAME, "/v0/messages", resp.status_code, {
        "model": model,
        "prompt_tokens": usage.get("input_tokens", 0),
        "completion_tokens": usage.get("output_tokens", 0),
        "stream": False,
    })

    if resp.status_code >= 400:
        raise HTTPException(status_code=resp.status_code, detail=resp_json)

    return resp_json


@router.post("/v0/messages/count_tokens")
async def anthropic_count_tokens(
    request: Request,
    user: User = Depends(get_current_user_claude),
):
    """
    轻量转发，不计入配额（跟聊天请求本身比起来量级很小，
    如果你希望它也扣配额，把 require_quota 那行从上面搬一份过来即可）。
    """
    body = await request.json()
    upstream_url = f"{config.CLAUDE_UPSTREAM_BASE}/v0/messages/count_tokens"
    headers = {"x-api-key": config.CLAUDE_UPSTREAM_API_KEY, "content-type": "application/json"}

    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(upstream_url, json=body, headers=headers)

    try:
        return resp.json()
    except Exception:
        return {"input_tokens": 1}