"""
plugins/sd_proxy/config.py

Stable Diffusion Proxy 配置
"""

DISPLAY_NAME = "GPT IMAGE 2"
DESCRIPTION = "强大的图片编辑模型"

# 每个 API Key 每天 50 次
QUOTA_DEFAULT = 15


BACKEND_BASE = "http://localhost:8009/v1"
BACKEND_KEY  = ""



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
        data={"prompt": "画出全身，三视图，给出完整的表情差分和服饰构成。包括眼睛、发型、发色等特征点要素需要单独列出来。角色参考图1，格式参考图2", "aspect_ratio": "16:9"},
        timeout=None,
        headers=headers,
    )
print(resp.json()["data"][0]["url"])

# ======= 文本转图像 =======
import httpx

base_url="http://api.apollodorus.xyz/v1/images/generations"
your_api_key = "sk-xxxx"
headers={"Authorization": f"Bearer {your_api_key}"}
# 文生图
resp = httpx.post(
    base_url,
    json={
        "prompt": "a cat sitting on a table, digital art",
        "aspect_ratio": "1:1",
        "response_format": "url", # 或 "b64_json"
        "n": 1,
    },
    headers=headers,
    timeout=None
)
print(resp.status_code)
print(resp.json()["data"][0]["url"])
"""