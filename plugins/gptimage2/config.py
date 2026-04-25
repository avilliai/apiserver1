"""
plugins/sd_proxy/config.py

Stable Diffusion Proxy 配置
"""

DISPLAY_NAME = "GPT IMAGE 2 图像生成"
DESCRIPTION = "强大的图片编辑模型"

# 每个 API Key 每天 50 次
QUOTA_DEFAULT = 25


BACKEND_BASE = "http://localhost:8009/v1"
BACKEND_KEY  = ""

POST_TEST={
    "headers": {"Authorization": f"Bearer apikey"},
    "type": "post",
    "end_point": "/v1/images/generations",
    "params": {
        "prompt": "a cat sitting on a table, digital art",
        "aspect_ratio": "1:1",
        "response_format": "url", # 或 "b64_json"
        "model": "gpt-image-2",
        "n": 1,
    }
}

EXAMPLE = """
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
        "model": "gpt-image-2",
        "n": 1,
    },
    headers=headers,
    timeout=None
)
print(resp.status_code)
print(resp.json()["data"][0]["url"])
"""