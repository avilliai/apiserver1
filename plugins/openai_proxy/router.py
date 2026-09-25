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
import json
import time

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db, User
from core.quota import get_current_user, require_quota, log_request
from plugins.openai_proxy import config

import logging

logger = logging.getLogger(__name__)

PLUGIN_PREFIX = ""
PLUGIN_NAME = "openai_proxy"

# 流式响应中，即使 HTTP 状态码是 200，也可能在首个 SSE 事件里内嵌错误，
# 或者上游（例如经过 Cloudflare Tunnel 的 origin 超时）直接返回一段 HTML 错误页。
# 这个值控制针对这类"伪 200 / 网关错误"的最大重试次数。
MAX_STREAM_ERROR_RETRIES = 3

# 非流式请求遇到上游错误时的最大重试次数。
MAX_REQUEST_RETRIES = 3

# 并发与超时控制：最多同时发起 6 个请求，超出的排队等待，总超时（含排队与请求）为 150 秒。
MAX_CONCURRENT_REQUESTS = 6
QUEUE_TIMEOUT_SECONDS = 150.0

_request_semaphore: asyncio.Semaphore | None = None


def _get_request_semaphore() -> asyncio.Semaphore:
    global _request_semaphore
    if _request_semaphore is None:
        _request_semaphore = asyncio.Semaphore(MAX_CONCURRENT_REQUESTS)
    return _request_semaphore


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


def _extract_sse_payload(line: str) -> str:
    """
    从一行 SSE 文本中提取 data 部分（去掉 "data:" 前缀），
    如果不是 data 行则原样返回去除首尾空白后的内容。
    """
    stripped = line.strip()
    if stripped.startswith("data:"):
        return stripped[len("data:"):].strip()
    return stripped


def _looks_like_html_error(text) -> bool:
    """
    判断一段文本是否是 HTML 错误页（典型如 Cloudflare 524/502 的网关超时页面）。
    上游经 Cloudflare Tunnel 暴露时，origin 超时会返回一段 HTML 而非 JSON，
    HTTP 状态码有时还会在中间层被改写成 200，因此需要按内容识别。
    """
    if not isinstance(text, str):
        return False
    lowered = text[:2000].lower()
    return (
        "<!doctype html" in lowered
        or "<html" in lowered
        or "error code 524" in lowered
        or "a timeout occurred" in lowered
        or "cf-error" in lowered
        or "cloudflare" in lowered and "error" in lowered
    )


def _is_stream_error_payload(payload: str) -> bool:
    """
    判断某个 SSE data payload 是否代表上游返回的"伪 200"错误：
      - 事件体是 JSON 且包含 "error" 字段，或
      - 事件体其实是一段 HTML 网关错误页（非 JSON）。
    """
    if not payload or payload == "[DONE]":
        return False
    if _looks_like_html_error(payload):
        return True
    try:
        parsed = json.loads(payload)
    except Exception:
        return False
    return _is_error_body(parsed)


def _is_error_body(parsed) -> bool:
    """
    判断一个已解析的 JSON 响应体是否代表错误
    （无论 HTTP 状态码是多少，只要 body 里带 "error" 字段就算）。
    用于非流式响应中"状态码 200 但内容是错误"的情况。
    """
    return isinstance(parsed, dict) and "error" in parsed


async def _open_stream_with_retry(
    upstream_url: str,
    upstream_body: dict,
    headers: dict,
    max_retries: int = MAX_STREAM_ERROR_RETRIES,
):
    """
    打开上游流式连接，并在开始向客户端转发之前完成错误校验与重试。

    校验项（任一命中即视为上游错误，关闭连接后重试）：
      1. HTTP 状态码 >= 400（例如 Cloudflare 524 网关超时）。
      2. Content-Type 是 text/html（网关错误页，状态码可能被改写成 200）。
      3. 首个非空 SSE 行是"伪 200"错误（JSON 里含 error，或本身是 HTML）。
      4. 建立连接时抛出网络异常。

    成功时返回 (client, stream_cm, response, line_iter, first_line)，调用方负责
    在消费完毕后关闭 stream_cm 与 client。first_line 是已经预读出来的第一行
    （可能为 None），需要由调用方先行 yield，再继续消费 line_iter。

    重试全部失败时抛出 HTTPException，此时尚未开始流式响应，客户端能拿到正确状态码。
    """
    attempt = 0
    last_status = 502
    last_body = ""

    while attempt <= max_retries:
        client = httpx.AsyncClient(timeout=None)
        stream_cm = client.stream("POST", upstream_url, json=upstream_body, headers=headers)
        try:
            resp = await stream_cm.__aenter__()
        except Exception as exc:
            logger.error(
                f"[STREAM CONNECT ERROR] {exc} (attempt={attempt})"
            )
            await client.aclose()
            last_status = 502
            last_body = str(exc)
            attempt += 1
            continue

        content_type = resp.headers.get("content-type", "").lower()
        bad_status = resp.status_code >= 400
        html_error = "text/html" in content_type

        if bad_status or html_error:
            body_bytes = await resp.aread()
            body_text = body_bytes.decode("utf-8", "replace")
            logger.error(
                f"[STREAM UPSTREAM ERROR] status={resp.status_code} "
                f"content_type={content_type!r} attempt={attempt} "
                f"body={body_text[:300]!r}"
            )
            last_status = resp.status_code if bad_status else 502
            last_body = body_text
            await stream_cm.__aexit__(None, None, None)
            await client.aclose()
            attempt += 1
            continue

        # 状态码与 Content-Type 都正常，再预读第一行，兜住"伪 200"错误。
        line_iter = resp.aiter_lines()
        first_line = None
        try:
            async for line in line_iter:
                if not line:
                    continue
                first_line = line
                break
        except Exception as exc:
            logger.error(f"[STREAM READ ERROR] {exc} (attempt={attempt})")
            await stream_cm.__aexit__(None, None, None)
            await client.aclose()
            last_status = 502
            last_body = str(exc)
            attempt += 1
            continue

        if first_line is not None:
            payload = _extract_sse_payload(first_line)
            if _is_stream_error_payload(payload):
                logger.error(
                    f"[STREAM UPSTREAM ERROR embedded] {payload[:300]!r} "
                    f"(attempt={attempt})"
                )
                last_status = 502
                last_body = payload
                await stream_cm.__aexit__(None, None, None)
                await client.aclose()
                attempt += 1
                continue

        return client, stream_cm, resp, line_iter, first_line

    # 重试用尽：此时还没开始流式，返回真实错误码。
    status_code = last_status if last_status >= 400 else 502
    detail = {"error": last_body[:2000] or "upstream stream error"}
    raise HTTPException(status_code=status_code, detail=detail)


async def _proxy_request_core(
    path: str,
    body: dict,
    user: User,
    db: AsyncSession,
    start_time: float,
    retries=0
):
    elapsed = time.monotonic() - start_time
    remaining_time = max(0.0, QUEUE_TIMEOUT_SECONDS - elapsed)
    if remaining_time <= 0:
        raise asyncio.TimeoutError("Request exceeded total timeout limit of 150s.")

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
        # 在开始向客户端流式转发之前，先完成上游连接、状态码与首行错误校验并重试。
        # 只有确认上游正常后才创建 StreamingResponse，避免把 Cloudflare 524 之类的
        # HTML 错误页当成 200 内容原样吐给客户端。
        client, stream_cm, resp, line_iter, first_line = await _open_stream_with_retry(
            upstream_url, upstream_body, headers, MAX_STREAM_ERROR_RETRIES
        )
        logger.info(f"[UPSTREAM HEADERS] {resp.headers}")

        async def generate():
            try:
                if first_line is not None:
                    yield f"{first_line.strip()}\n\n"
                while True:
                    cur_elapsed = time.monotonic() - start_time
                    rem = QUEUE_TIMEOUT_SECONDS - cur_elapsed
                    if rem <= 0:
                        logger.error(f"[STREAM TIMEOUT] Stream exceeded total timeout of {QUEUE_TIMEOUT_SECONDS}s.")
                        raise asyncio.TimeoutError("Stream exceeded total timeout limit of 150s.")
                    try:
                        line = await asyncio.wait_for(line_iter.__anext__(), timeout=rem)
                    except StopAsyncIteration:
                        break
                    if not line:
                        continue
                    yield f"{line.strip()}\n\n"
            except Exception as e:
                logger.error(f"[STREAM ERROR] {e}")
                raise
            finally:
                try:
                    await stream_cm.__aexit__(None, None, None)
                except Exception:
                    pass
                await client.aclose()

        return StreamingResponse(generate(), media_type="text/event-stream")

    else:
        elapsed_now = time.monotonic() - start_time
        call_timeout = max(0.001, QUEUE_TIMEOUT_SECONDS - elapsed_now)
        async with httpx.AsyncClient(timeout=call_timeout) as client:
            resp = await client.post(upstream_url, json=upstream_body, headers=headers)

        content_type = resp.headers.get("content-type", "").lower()
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

        # 判定上游是否失败：真实错误码、body 里带 error 字段（含解析失败时合成的），
        # 或 Content-Type/正文其实是 HTML 网关错误页（可能被改写成 200）。
        html_error = "text/html" in content_type or _looks_like_html_error(
            resp_json.get("error") if isinstance(resp_json, dict) else resp.text
        )
        is_upstream_error = (
            resp.status_code >= 400
            or _is_error_body(resp_json)
            or html_error
        )

        if is_upstream_error:
            if retries >= MAX_REQUEST_RETRIES:
                status_code = resp.status_code if resp.status_code >= 400 else 502
                raise HTTPException(status_code=status_code, detail=resp_json)
            else:
                logger.error(
                    f"[UPSTREAM ERROR] status={resp.status_code} "
                    f"content_type={content_type!r} html_error={html_error} | "
                    f"RETRYING ({retries + 1}/{MAX_REQUEST_RETRIES})......."
                )
                return await _proxy_request_core(path, body, user, db, start_time, retries + 1)

        return resp_json


async def _proxy_request(
    path: str,
    body: dict,
    user: User,
    db: AsyncSession,
):
    """
    控制最大并发为 6 个请求，超出的排队等待。
    排队和执行过程总超时为 150 秒，超时自动取消并释放并发槽。
    """
    sem = _get_request_semaphore()
    start_time = time.monotonic()

    # 排队获取并发槽位（最多排队 150 秒）
    try:
        await asyncio.wait_for(sem.acquire(), timeout=QUEUE_TIMEOUT_SECONDS)
    except asyncio.TimeoutError:
        logger.warning(f"[CONCURRENCY QUEUE TIMEOUT] Request queued for over {QUEUE_TIMEOUT_SECONDS}s, aborted.")
        raise HTTPException(
            status_code=504,
            detail=f"Too many concurrent requests, queue wait timed out after {int(QUEUE_TIMEOUT_SECONDS)}s."
        )

    released = False

    def release_sem():
        nonlocal released
        if not released:
            released = True
            sem.release()

    try:
        elapsed = time.monotonic() - start_time
        remaining = max(0.0, QUEUE_TIMEOUT_SECONDS - elapsed)
        if remaining <= 0:
            raise asyncio.TimeoutError("Request timed out before execution.")

        result = await asyncio.wait_for(
            _proxy_request_core(path, body, user, db, start_time=start_time, retries=0),
            timeout=remaining
        )

        # 流式响应需在流完全消费完毕或连接中断时释放并发槽
        if isinstance(result, StreamingResponse):
            original_body_iterator = result.body_iterator

            async def wrapped_body_iterator():
                try:
                    async for chunk in original_body_iterator:
                        yield chunk
                finally:
                    release_sem()

            result.body_iterator = wrapped_body_iterator()
            return result
        else:
            release_sem()
            return result

    except asyncio.TimeoutError:
        release_sem()
        logger.warning(f"[REQUEST TIMEOUT] Request timed out after {QUEUE_TIMEOUT_SECONDS}s.")
        raise HTTPException(
            status_code=504,
            detail=f"Request timed out after {int(QUEUE_TIMEOUT_SECONDS)}s."
        )
    except Exception:
        release_sem()
        raise


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
