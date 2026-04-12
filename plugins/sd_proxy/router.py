"""
plugins/sd_proxy/router.py

Stable Diffusion API Proxy
支持：
- txt2img
- img2img
- loras
- sd-models
- png-info
"""

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db, User
from core.quota import get_current_user, require_quota, log_request
from plugins.sd_proxy import config
import logging
logger = logging.getLogger(__name__)

PLUGIN_NAME = "sd_proxy"
PLUGIN_PREFIX = ""
router = APIRouter()


async def _forward_request(
    path: str,
    request: Request,
    user: User,
    db: AsyncSession,
):
    url = f"{config.UPSTREAM_BASE_URL}{path}"

    headers = {
        "Content-Type": "application/json",
    }

    if config.UPSTREAM_API_KEY:
        headers["Authorization"] = f"Bearer {config.UPSTREAM_API_KEY}"

    try:
        body = await request.json()
    except Exception:
        body = None
    logger.info(f"📥 收到请求: {request.method} {request.url}")
    logger.info(f"👤 用户: {getattr(user, 'id', None)}")
    logger.info(f"➡️ 转发到: {url}")

    def fix_paramters(body: dict):
        ideal_structure = {'denoising_strength': 0.7, 'enable_hr': 'false', 'hr_scale': 1.5, 'hr_second_pass_steps': 15,
                           'hr_upscaler': 'SwinIR_4x',
                           'prompt': 'rating:general, best quality, very aesthetic, absurdres',
                           'negative_prompt': 'blurry, lowres, error, film grain, scan artifacts, worst quality, bad quality, jpeg artifacts, very displeasing, chromatic aberration, logo, dated, signature, multiple views, gigantic breasts',
                           'seed': -1, 'batch_size': 1, 'n_iter': 1, 'steps': 28, 'save_images': True, 'cfg_scale': 4.5,
                           'width': 1024, 'height': 1536, 'restore_faces': False, 'tiling': False,
                           'sampler_name': 'Euler a', 'scheduler': 'Automatic', 'clip_skip_steps': 2,
                           'override_settings': {'CLIP_stop_at_last_layers': 2,
                                                 'sd_model_checkpoint': 'waillustriousSDXL_v160.safetensors'},
                           'override_settings_restore_afterwards': False}
        for key, value in ideal_structure.items():
            if key not in body:
                body[key] = value
            if key == "prompt":
                body["prompt"] = body['prompt'] + value
    fix_paramters(body)
    async with httpx.AsyncClient(timeout=300.0) as client:
        resp = await client.post(url, json=body, headers=headers)

        try:
            data = resp.json()
        except Exception:
            data = {"raw": resp.text}

        # 记录调用
        await log_request(db, user, PLUGIN_NAME, path, resp.status_code, {
            "endpoint": path,
        })

        if resp.status_code >= 400:
            raise HTTPException(status_code=resp.status_code, detail=data)

        return data


# ---------- SD Endpoints ----------

@router.post("/sdapi/v1/txt2img")
async def txt2img(
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _quota=Depends(require_quota(PLUGIN_NAME)),
):
    return await _forward_request("/sdapi/v1/txt2img", request, user, db)


@router.post("/sdapi/v1/img2img")
async def img2img(
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _quota=Depends(require_quota(PLUGIN_NAME)),
):
    return await _forward_request("/sdapi/v1/img2img", request, user, db)


@router.get("/sdapi/v1/loras")
async def loras(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _quota=Depends(require_quota(PLUGIN_NAME)),
):
    url = f"{config.UPSTREAM_BASE_URL}/sdapi/v1/loras"

    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.get(url)

        data = resp.json()

        await log_request(db, user, PLUGIN_NAME, "/loras", resp.status_code, {})

        return data


@router.get("/sdapi/v1/sd-models")
async def models(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _quota=Depends(require_quota(PLUGIN_NAME)),
):
    url = f"{config.UPSTREAM_BASE_URL}/sdapi/v1/sd-models"

    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.get(url)

        data = resp.json()

        await log_request(db, user, PLUGIN_NAME, "/sd-models", resp.status_code, {})

        return data


@router.post("/sdapi/v1/png-info")
async def png_info(
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _quota=Depends(require_quota(PLUGIN_NAME)),
):
    return await _forward_request("/sdapi/v1/png-info", request, user, db)