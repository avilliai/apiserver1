DISPLAY_NAME = "Hololive TTS 文本转语音"
DESCRIPTION = "文本转语言"
# 每个 API Key 每天 50 次
QUOTA_DEFAULT = 3000



POST_TEST = {
    "headers": {"Authorization": f"Bearer apikey"},
    "type": "post",
    "end_point": "/tts",
    "params": {
            "text": "早上好，今天你起的好早",
            "speaker": "AZKI",
        "lang": "JP"
        }
}
EXAMPLE = """
import base64
import requests
BASE = "http://api.apollodorus.xyz"
apikey='sk-xxxx'
r= requests.post(
    BASE + "/tts",
    json = {
            "text": "早上好，今天你起的好早",
            "speaker": "AZKI",
        "lang": "JP"
        },
    headers={"Authorization":f"Bearer {apikey}"},
    timeout=1000)
print(r.json())
"""
