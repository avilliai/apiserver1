"""
plugins/sd_proxy/config.py

Stable Diffusion Proxy 配置
"""

DISPLAY_NAME = "Stable Diffusion 图像生成"
DESCRIPTION = "基于stable diffusion的图像生成"

# 每个 API Key 每天 50 次
QUOTA_DEFAULT = 30
RPM=3  #每分钟请求次数
# 统一转发到你的 SD 服务
UPSTREAM_BASE_URL = "http://localhost:3529"

# 是否需要 API KEY（一般 SD WebUI 不需要，可以留空）
UPSTREAM_API_KEY = ""

# 记录字段
DB_EXTRA_FIELDS = ["endpoint"]

POST_TEST = {
    "headers": {"Authorization": f"Bearer apikey"},
    "type": "post",
    "end_point": "/sdapi/v1/txt2img",
    "params": {"prompt": "1girl"}
}
EXAMPLE = """
import base64
import requests
BASE = "http://api.apollodorus.xyz"
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

