"""
plugins/sd_proxy/config.py

Stable Diffusion Proxy 配置
"""

DISPLAY_NAME = "GPT IMAGE 2"
DESCRIPTION = "强大的图片编辑模型"

# 每个 API Key 每天 50 次
QUOTA_DEFAULT = 10

# 统一转发到你的 SD 服务
UPSTREAM_BASE_URL = "http://localhost:8009"

# 是否需要 API KEY（一般 SD WebUI 不需要，可以留空）
UPSTREAM_API_KEY = ""



EXAMPLE = """
import base64
import requests
BASE = "http://apollodorus.xyz:8080"
apikey='sk-xxxx'
prompt="一个蓝色渐变头发的二次元女孩，日漫，平涂风格"
r= requests.post(
    BASE + "/v1/images/generations",
    json = {
        "prompt": prompt,
        "aspect_ratio": "1:1",
        "quality": "medium"
    },
    headers={"Authorization":f"Bearer {apikey}"},
    timeout=1000)
img_url=r.json()["data"][0]["url"]

# =====================
# 图片编辑
# =====================
import requests
import base64
import os


def call_image_edit(image_path, prompt):
    url = "http://apollodorus.xyz:8080/v1/images/generations"

    if not os.path.exists(image_path):
        print("文件不存在")
        return

    # 读取图片并转 base64
    with open(image_path, "rb") as f:
        base64_str = base64.b64encode(f.read()).decode("utf-8")

    image_input = f"data:image/png;base64,{base64_str}"

    payload = {
        "prompt": prompt,
        "image": image_input,
        "aspect_ratio": "1:1",
        "quality": "medium"
    }

    try:
        resp = requests.post(url, json=payload, timeout=180)

        print("状态码:", resp.status_code)

        if resp.status_code == 200:
            data = resp.json()
            print("结果:", data)

            img_url = data["data"][0]["url"]
            print("生成图片:", img_url)
        else:
            print("错误:", resp.text)

    except Exception as e:
        print("请求异常:", e)


if __name__ == "__main__":
    call_image_edit(
        "test.png",
        "把这个人变成哭脸"
    )
"""