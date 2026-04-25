"""
plugins/sd_proxy/config.py

Stable Diffusion Proxy 配置
"""

DISPLAY_NAME = "GPT IMAGE 2 图像编辑"
DESCRIPTION = "强大的图片编辑模型"

# 每个 API Key 每天 50 次
QUOTA_DEFAULT = 25

BACKEND_BASE = "http://localhost:8009/v1"
BACKEND_KEY = ""

POST_TEST = {
    "headers": {"Authorization": f"Bearer apikey"},
    "type": "post",
    "end_point": "/v1/images/edits",
    "params": {"prompt": "画出全身，三视图，给出完整的表情差分和服饰构成。包括眼睛、发型、发色等特征点要素需要单独列出来。角色参考图1，格式参考图2", "aspect_ratio": "1:1","model": "gpt-image-2"},
    "files": ["images"]
}

EXAMPLE = """
# ======= 图像编辑 =====
import httpx

base_url="http://api.apollodorus.xyz/v1"
your_api_key = "sk-xxxx"
headers={"Authorization": f"Bearer {your_api_key}"}

with open("yucca.png", "rb") as f1 , open("img3.png", "rb") as f:

    resp = httpx.post(
        f"{base_url}/images/edits",
        files=[
            ("images", ("yucca.png", f1, "image/png")),
            ("images", ("img3.png", f, "image/png"))
        ],
        data={"prompt": "画出全身，三视图，给出完整的表情差分和服饰构成。包括眼睛、发型、发色等特征点要素需要单独列出来。角色参考图1，格式参考图2", "aspect_ratio": "1:1","model": "gpt-image-2"},
        timeout=None,
        headers=headers,
    )
print(resp.json()["data"][0]["url"])
"""