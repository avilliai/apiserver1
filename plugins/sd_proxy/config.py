"""
plugins/sd_proxy/config.py

Stable Diffusion Proxy 配置
"""

DISPLAY_NAME = "Stable Diffusion Proxy"
DESCRIPTION = "Proxy for SD WebUI APIs (txt2img, img2img, loras, models, png-info)"

# 每个 API Key 每天 50 次
QUOTA_DEFAULT = 20

# 统一转发到你的 SD 服务
UPSTREAM_BASE_URL = "http://localhost:3529"

# 是否需要 API KEY（一般 SD WebUI 不需要，可以留空）
UPSTREAM_API_KEY = ""

# 记录字段
DB_EXTRA_FIELDS = ["endpoint"]

EXAMPLE = """
import base64
import requests
BASE = "http://apollodorus.xyz:8080"
apikey='sk-xxxx'
r= requests.post(
    BASE + "/sdapi/v1/txt2img",
    json = {"prompt": "1girl"},
    headers={"Authorization":f"Bearer {apikey}"},
    timeout=1000)
img_b64=r.json()['images'][0]
image_data = base64.b64decode(img_b64)
with open("test.jpg", "wb") as f:
    f.write(image_data)
"""

