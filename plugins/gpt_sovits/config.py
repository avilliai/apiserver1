"""
plugins/gptsovits/config.py

GPT-SoVITS 本地 TTS 配置
"""

DISPLAY_NAME = "GPT-SoVITS"
DESCRIPTION  = "Eridanus tts_v2中配置 base_url: http://api.apollodorus.xyz apikey: 你自己申请的apikey"

# 每个 API Key 每天默认配额
QUOTA_DEFAULT = 3000

# GPT-SoVITS 服务地址
BACKEND_BASE = "http://127.0.0.1:3529"

# 参考音频配置（固定在服务端，按需修改）
REF_AUDIO_PATH = "output/slicer_opt/output.wav_0009342720_0009558400.wav"
PROMPT_TEXT    = "怎么啊？如果有你在也不放心，那就干脆给我也装个限制器或者炸弹喽。"
PROMPT_LANG    = "zh"

# /tts 接口的默认推理参数。
# 客户端请求体中若携带同名字段，会覆盖这里的默认值；不携带则使用默认值补全。
# 字段含义详见 GPT-SoVITS api_v2.py 文档。
TTS_DEFAULTS = {
    "ref_audio_path":      REF_AUDIO_PATH,
    "aux_ref_audio_paths": [],
    "prompt_text":         PROMPT_TEXT,
    "prompt_lang":         PROMPT_LANG,
    "top_k":               15,
    "top_p":               1,
    "temperature":         1,
    "text_split_method":   "cut5",
    "batch_size":          1,
    "batch_threshold":     0.75,
    "split_bucket":        True,
    "speed_factor":        1.0,
    "fragment_interval":   0.3,
    "seed":                -1,
    "media_type":          "wav",
    "streaming_mode":      False,
    "parallel_infer":      False,
    "repetition_penalty":  1.35,
    "sample_steps":        32,
    "super_sampling":      False,
    "overlap_length":      2,
    "min_chunk_length":    16,
}

# 客户端被允许覆盖的字段白名单（text / text_lang 单独处理，不在此列表中）
TTS_OVERRIDABLE_FIELDS = set(TTS_DEFAULTS.keys())

POST_TEST = {
    "headers": {"Authorization": "Bearer apikey"},
    "type": "post",
    "end_point": "/gptsovits/tts",
    "params": {
        "text":      "你好，世界！",
        "text_lang": "zh",
    },
}

EXAMPLE = """
import requests

BASE    = "http://api.apollodorus.xyz"
API_KEY = "sk-xxxx"

r = requests.post(
    BASE + "/gptsovits/tts",
    json={
        "text":      "拉海洛来了个救世主",
        "text_lang": "zh",   # zh / en / ja / auto
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