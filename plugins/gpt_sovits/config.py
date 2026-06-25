DISPLAY_NAME = "GPT-SoVITS 文本转语音"
DESCRIPTION = "基于 GPT-SoVITS 的本地 TTS，直接返回 WAV 音频"

# 每个 API Key 每天默认配额
QUOTA_DEFAULT = 1000

# GPT-SoVITS 服务地址
BACKEND_BASE = "http://127.0.0.1:3529"

# 参考音频配置（固定在服务端，按需修改）
REF_AUDIO_PATH = "output/slicer_opt/output.wav_0009342720_0009558400.wav"
PROMPT_TEXT    = "怎么啊？如果有你在也不放心，那就干脆给我也装个限制器或者炸弹喽。"
PROMPT_LANG    = "zh"

POST_TEST = {
    "headers": {"Authorization": "Bearer apikey"},
    "type": "get",
    "end_point": "/gptsovits/tts",
    "params": {
        "text": "你好，世界！",
        "text_lang": "zh",
    },
}

EXAMPLE = """
import requests

BASE    = "http://api.apollodorus.xyz"
API_KEY = "sk-xxxx"

r = requests.get(
    BASE + "/gptsovits/tts",
    params={
        "text":      "拉海洛来了个救世主",
        "text_lang": "zh",          # zh / en / ja
    },
    headers={"Authorization": f"Bearer {API_KEY}"},
    timeout=120,
)

if r.status_code == 200:
    with open("output.wav", "wb") as f:
        f.write(r.content)
    print("保存成功：output.wav")
else:
    print("失败：", r.json())
"""