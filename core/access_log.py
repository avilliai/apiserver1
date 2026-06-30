"""
core/access_log.py — 请求审计中间件 + IP 封禁拦截（纯 ASGI 实现）

职责：
1. 为每个"网关 API 调用"记录一行 access_logs：发起用户 / IP / 接口 /
   请求参数 / 返回结果。写入独立的 access_logs 表，不污染现有 request_logs
   统计（避免与各插件 router 里 log_request 的写入重复计数）。
2. 承载管理员"一键封禁"的 IP 拦截：内存集 _banned_ips 启动时从 banned_ips
   表载入，命中的 IP 直接 403。

为什么用纯 ASGI 而非 BaseHTTPMiddleware：能逐块 tee 请求/响应字节流，
即时转发每个 chunk，从而不破坏 openai_proxy 的 SSE 流式响应。

可读性：body 以原始 UTF-8 文本存储（非 \\uXXXX 转义）；二进制/过大内容做
占位与截断，避免日志爆量。
"""
import hashlib
import json
import logging
import time

from sqlalchemy import select

from core.database import AsyncSessionLocal, AccessLog, ApiKey, User, BannedIp
from core.auth_utils import decode_token

logger = logging.getLogger(__name__)

# ── 配置 ──────────────────────────────────────────────────────────────────
MAX_BODY = 16 * 1024  # 请求/响应体各自最多截留 16KB

# 不记录这些前缀的请求：管理面板自身 / 认证(含密码) / 静态资源 / 文档。
# 其余即为真正的"网关 API 调用"（openai 代理 /v1/* 与插件 /api/v1/<plugin>/*）。
SKIP_PREFIXES = (
    "/api/auth", "/api/admin", "/api/user", "/api/plugins", "/api/health",
    "/static", "/docs", "/openapi.json", "/redoc", "/favicon.ico",
    "/.well-known",   # 浏览器/devtools 探针噪音
)
SKIP_EXACT = {"", "/"}

# 这些 content-type 视为二进制，不存原文，仅存占位描述
_BINARY_CT_PREFIXES = ("image/", "audio/", "video/", "application/octet-stream")


def _is_binary_ct(ct: str) -> bool:
    ct = (ct or "").lower()
    return any(ct.startswith(p) for p in _BINARY_CT_PREFIXES) or "multipart/form-data" in ct


def _should_skip(path: str) -> bool:
    if path in SKIP_EXACT:
        return True
    return any(path.startswith(p) for p in SKIP_PREFIXES)


def _plugin_from_path(path: str) -> str:
    """
    判定请求归属的插件。优先用「实际命中的路由」（启动时由 build_route_map
    收集的 路径正则→插件名 映射，来源 include_router(tags=[name])），
    从而正确区分同样挂在 /v1 下的不同插件（如 gptimage2 vs openai_proxy）；
    无匹配时回退到路径启发式。
    """
    for regex, name in _route_plugins:
        try:
            if regex.match(path):
                return name
        except Exception:
            continue
    if path.startswith("/api/v1/"):
        parts = path.split("/")
        if len(parts) >= 4 and parts[3]:
            return parts[3]
    if path.startswith("/v1/"):
        return "openai_proxy"
    parts = [p for p in path.split("/") if p]
    return parts[0] if parts else "unknown"


# ── 路由 → 插件 映射（启动后由 main.build_route_map 填充）──────────────────────
_route_plugins: list = []


def build_route_map(app) -> None:
    """在所有路由注册完成后调用：收集 (编译后的路径正则, 插件名/tag)。"""
    _route_plugins.clear()
    for route in getattr(app, "routes", []):
        regex = getattr(route, "path_regex", None)
        tags = getattr(route, "tags", None)
        if regex is not None and tags:
            _route_plugins.append((regex, str(tags[0])))
    logger.info(f"🧭 Route→plugin map built: {len(_route_plugins)} routes")


# ── 内存封禁集（来源：banned_ips 表）────────────────────────────────────────
_banned_ips: set[str] = set()


async def load_banned_ips() -> None:
    """启动时从 DB 载入全部被封 IP 到内存集（由 main.py lifespan 调用）。"""
    try:
        async with AsyncSessionLocal() as db:
            rows = (await db.execute(select(BannedIp.ip_address))).scalars().all()
        _banned_ips.clear()
        _banned_ips.update(ip for ip in rows if ip)
        logger.info(f"🔒 Loaded {len(_banned_ips)} banned IP(s) from DB")
    except Exception as e:
        logger.warning(f"load_banned_ips failed: {e}")


def is_ip_banned(ip: str) -> bool:
    return ip in _banned_ips


def add_banned_ips(ips) -> None:
    for ip in ips:
        if ip:
            _banned_ips.add(ip)


def remove_banned_ip(ip: str) -> None:
    _banned_ips.discard(ip)


# ── 工具 ──────────────────────────────────────────────────────────────────
def _header_get(headers, name: bytes):
    for k, v in headers:
        if k == name:
            try:
                return v.decode("latin-1")
            except Exception:
                return None
    return None


def get_client_ip(headers, scope) -> str:
    """优先取代理头里的真实客户端 IP，回退到直连地址。"""
    xff = _header_get(headers, b"x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()
    xri = _header_get(headers, b"x-real-ip")
    if xri:
        return xri.strip()
    client = scope.get("client")
    return client[0] if client else "unknown"


def _decode_body(raw: bytes, content_type: str, truncated: bool) -> str:
    if not raw:
        return ""
    if _is_binary_ct(content_type):
        return f"[binary {content_type or 'unknown'} ~{len(raw)}+ bytes]"
    text = raw.decode("utf-8", errors="replace")
    # 规范化 JSON：把客户端用 ensure_ascii=True 序列化产生的 \uXXXX 转义还原为
    # 可读中文，既便于阅读也便于关键字检索。非 JSON / 截断的 body 原样保留。
    if not truncated:
        stripped = text.lstrip()
        if stripped[:1] in ("{", "["):
            try:
                text = json.dumps(json.loads(text), ensure_ascii=False)
            except Exception:
                pass
    if truncated:
        text += "\n...[truncated]"
    return text


async def _identify_user(headers, db):
    """
    复刻 core/quota.py::get_current_user 的最小识别逻辑。
    返回 (user_id | None, username, api_key_prefix | None)。
    """
    auth = _header_get(headers, b"authorization")
    if not auth or not auth.lower().startswith("bearer "):
        return None, "(anonymous)", None
    token = auth[7:].strip()
    try:
        if token.startswith("sk-"):
            key_hash = hashlib.sha256(token.encode()).hexdigest()
            api_key = (await db.execute(
                select(ApiKey).where(ApiKey.key_hash == key_hash)
            )).scalar_one_or_none()
            if not api_key:
                return None, "(invalid key)", token[:10]
            user = (await db.execute(
                select(User).where(User.id == api_key.user_id)
            )).scalar_one_or_none()
            return (api_key.user_id,
                    user.username if user else "(unknown)",
                    api_key.key_prefix)
        else:
            payload = decode_token(token)  # 无效 token 抛 HTTPException
            user_id = int(payload.get("sub", 0))
            user = (await db.execute(
                select(User).where(User.id == user_id)
            )).scalar_one_or_none()
            return (user_id if user else None,
                    user.username if user else "(unknown)",
                    None)
    except Exception:
        return None, "(unidentified)", None


class AccessLogMiddleware:
    """纯 ASGI 中间件：审计日志 + 被封 IP 拦截。"""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        headers = scope.get("headers", [])
        ip = get_client_ip(headers, scope)
        skip = _should_skip(path)

        # ── 被封 IP：仅拦截真正的 API 路径（避免误伤同 IP 的后台登录排查）──
        if is_ip_banned(ip) and not skip:
            started = time.time()
            await self._send_403(send)
            await self._safe_write(
                scope, ip, headers, status_code=403,
                req_text="[blocked: banned ip]", resp_text="", started=started,
            )
            return

        if skip:
            await self.app(scope, receive, send)
            return

        started = time.time()
        req_ct = _header_get(headers, b"content-type") or ""

        # ── tee 请求体（上限 MAX_BODY）──
        req_chunks, req_state = [], {"size": 0, "truncated": False}

        async def receive_wrapper():
            message = await receive()
            if message["type"] == "http.request":
                body = message.get("body", b"")
                if body and req_state["size"] < MAX_BODY:
                    take = body[: MAX_BODY - req_state["size"]]
                    req_chunks.append(take)
                    req_state["size"] += len(take)
                    if len(take) < len(body):
                        req_state["truncated"] = True
                elif body:
                    req_state["truncated"] = True
            return message

        # ── tee 响应体（每块即时转发，保留流式；上限 MAX_BODY）──
        resp_chunks = []
        resp_state = {"size": 0, "truncated": False, "status": 0, "ct": ""}

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                resp_state["status"] = message["status"]
                resp_state["ct"] = _header_get(message.get("headers", []), b"content-type") or ""
            elif message["type"] == "http.response.body":
                body = message.get("body", b"")
                if body and resp_state["size"] < MAX_BODY:
                    take = body[: MAX_BODY - resp_state["size"]]
                    resp_chunks.append(take)
                    resp_state["size"] += len(take)
                    if len(take) < len(body):
                        resp_state["truncated"] = True
                elif body:
                    resp_state["truncated"] = True
            await send(message)

        try:
            await self.app(scope, receive_wrapper, send_wrapper)
        finally:
            req_text = _decode_body(b"".join(req_chunks), req_ct, req_state["truncated"])
            if not req_text:
                qs = scope.get("query_string", b"").decode("utf-8", "replace")
                if qs:
                    req_text = "?" + qs
            resp_text = _decode_body(b"".join(resp_chunks), resp_state["ct"], resp_state["truncated"])
            await self._safe_write(
                scope, ip, headers, status_code=resp_state["status"],
                req_text=req_text, resp_text=resp_text, started=started,
            )

    async def _send_403(self, send):
        body = json.dumps({"detail": "Your IP has been banned."}).encode("utf-8")
        await send({
            "type": "http.response.start",
            "status": 403,
            "headers": [(b"content-type", b"application/json")],
        })
        await send({"type": "http.response.body", "body": body})

    async def _safe_write(self, scope, ip, headers, status_code, req_text, resp_text, started):
        """写一条 access_logs；任何异常都不得影响请求本身。"""
        try:
            path = scope.get("path", "")
            method = scope.get("method", "")
            async with AsyncSessionLocal() as db:
                user_id, username, api_key_prefix = await _identify_user(headers, db)
                db.add(AccessLog(
                    user_id=user_id,
                    username=username,
                    ip_address=ip,
                    method=method,
                    plugin=_plugin_from_path(path),
                    endpoint=path,
                    status_code=status_code,
                    request_body=req_text,
                    response_body=resp_text,
                    api_key_prefix=api_key_prefix,
                    duration_ms=int((time.time() - started) * 1000),
                ))
                await db.commit()
        except Exception as e:
            logger.warning(f"access log write failed: {e}")
