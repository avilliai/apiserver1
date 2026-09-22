"""
plugins/openai_proxy/config.py

Plugin configuration. This file is the ONLY place you need to edit for this plugins.
- QUOTA_DEFAULT: None = unlimited; any int = calls per user before 429
- DISPLAY_NAME / DESCRIPTION: shown in frontend UI automatically
- DB_EXTRA_FIELDS: optional metadata (informational, not auto-migrated)
"""

DISPLAY_NAME = "OpenAI Proxy v0"
DESCRIPTION = ("可用模型'deepseek/deepseek-v4-flash', 'google/gemini-2.5-flash-lite', 'openai/gpt-5.6-luna', 'openai/gpt-5-nano', 'zai/glm-5.3-flash', 'mistral/mistral-small-4', 'gpt-5.6-luna', 'gpt-5-nano', 'deepseek-v4-flash', 'gemini-2.5-flash-lite', 'glm-5.3-flash', 'mistral-small-4'")

# Set to None for unlimited, or an integer to cap per-user calls
QUOTA_DEFAULT = 1200

# Upstream routing table: model-prefix -> upstream base URL
# Add new model families here without touching any other file
UPSTREAM_ROUTES = {
    "deepseek":     "http://localhost:8077",
    "gpt":      "http://localhost:8077",
    "gemini":   "http://localhost:8077",
    "glm": "http://localhost:8077",
    "mistral":       "http://localhost:8077",
    "o3":       "http://localhost:8001",
}

# Your master API key injected into every upstream request
UPSTREAM_API_KEY = ""

# DB_EXTRA_FIELDS: informational, tracked in RequestLog.extra_json
DB_EXTRA_FIELDS = ["model", "prompt_tokens", "completion_tokens"]

POST_TEST = {
    "headers": {"Authorization": f"Bearer apikey"},
    "type": "post",
    "end_point": "/v0/chat/completions",
    "params": {
    "model": "deepseek-v4-flash",
    "messages": [
        {"role": "user", "content": "你好，简单介绍一下你自己"}
    ]
}
}

EXAMPLE = """
from openai import OpenAI

client = OpenAI(
    base_url="http://api.apollodorus.xyz/v0",
    api_key="sk-xxxx"
)

# Chat completion
response = client.chat.completions.create(
    model="deepseek-v4-flash",  # 有其他模型，很多，懒得写，自己试去吧
    messages=[{"role": "user", "content": "Hello!"}]
)
print(response.choices[0].message.content)

# ====== 自己调用 ======
import requests

url = "https://api.apollodorus.xyz/v0/chat/completions"

headers = {
    "Authorization": "Bearer YOUR_API_KEY",
    "Content-Type": "application/json"
}

data = {
    "model": "deepseek-v4-flash",
    "messages": [
        {"role": "user", "content": "你好，简单介绍一下你自己"}
    ]
}

response = requests.post(url, headers=headers, json=data)

print(response.status_code)
print(response.json())
"""
