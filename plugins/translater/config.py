
DISPLAY_NAME = "ai翻译器"
DESCRIPTION = "用ai将输入翻译为指定语言。"
# 每个 API Key 每天 50 次
QUOTA_DEFAULT = 3000



POST_TEST = {
    "headers": {"Authorization": f"Bearer apikey"},
    "type": "post",
    "end_point": "/translate",
    "params": {
            "text": "需要翻译的内容",
            "direction": "zh2ja"
        }
}
EXAMPLE = """
import base64
import requests
BASE = "http://api.apollodorus.xyz"
apikey='sk-xxxx'
r= requests.post(
    BASE + "/translate",
    json = {
            "text": "需要翻译的内容",
            "direction": "zh2en"  #| "en2zh" | "zh2ja" | "ja2zh"
        },
    headers={"Authorization":f"Bearer {apikey}"},
    timeout=1000)
print(r.json())
"""
