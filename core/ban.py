"""
core/ban.py — 自动封禁短时间内高失败率的 IP
"""
import json
import os
import time
from collections import defaultdict


from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
import logging
logger = logging.getLogger(__name__)

BANLIST_FILE = "banlist.json"
FAIL_WINDOW = 100          # 统计窗口（秒）
MIN_REQUESTS = 6          # 窗口内至少请求多少次才触发判断（太少不统计）
FAIL_RATE_THRESHOLD = 0.7 # 失败率超过此值触发封禁
BAN_DURATION = None  #永不解封

FAIL_CODES = {404}


_request_log: dict[str, list] = defaultdict(list)


_banlist: dict[str, float] = {}

def cleanup_request_log():
    now = time.time()
    dead = [ip for ip, log in _request_log.items() if not log or now - log[-1][0] > FAIL_WINDOW]
    for ip in dead:
        del _request_log[ip]
    if dead:
        logger.info(f"🧹 Cleaned {len(dead)} stale IPs from request log")
def _load_banlist():
    if os.path.exists(BANLIST_FILE):
        with open(BANLIST_FILE, "r") as f:
            _banlist.update(json.load(f))

def _save_banlist():
    with open(BANLIST_FILE, "w") as f:
        json.dump(_banlist, f, indent=2)

def _ban_ip(ip: str):
    _banlist[ip] = "permanent"
    _save_banlist()
    logger.warning(f"🚫 Permanently banned IP: {ip}")

def is_banned(ip: str) -> bool:
    until = _banlist.get(ip)
    if until is None:
        return False
    if until == "permanent":
        return True
    if time.time() < until:
        return True
    del _banlist[ip]
    _save_banlist()
    return False

def _record_and_check(ip: str, is_fail: bool):
    now = time.time()
    # 只保留窗口内的记录
    log = _request_log[ip]
    _request_log[ip] = [(t, f) for t, f in log if now - t < FAIL_WINDOW]
    _request_log[ip].append((now, is_fail))

    total = len(_request_log[ip])
    if total < MIN_REQUESTS:
        return  # 请求数不够，不判断

    fail_count = sum(1 for _, f in _request_log[ip] if f)
    if fail_count / total >= FAIL_RATE_THRESHOLD:
        _ban_ip(ip)


class AutoBanMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        ip = request.client.host

        if is_banned(ip):
            logger.warning(f"{ip} is banned")
            return JSONResponse(status_code=403, content={"detail": "Forbidden"})

        response = await call_next(request)

        _record_and_check(ip, is_fail=response.status_code in FAIL_CODES)

        return response


_load_banlist()