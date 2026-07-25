"""
plugins/openai_proxy/config.py

Plugin configuration. This file is the ONLY place you need to edit for this plugins.
- QUOTA_DEFAULT: None = unlimited; any int = calls per user before 429
- DISPLAY_NAME / DESCRIPTION: shown in frontend UI automatically
- DB_EXTRA_FIELDS: optional metadata (informational, not auto-migrated)
"""

DISPLAY_NAME = "OpenAI Proxy"
DESCRIPTION = ("注意，此接口是http://api.apollodorus.xyz/v0  可用模型'openrouter:openai/gpt-5.4-nano',''openrouter:openai/gpt-4o-mini','openrouter:deepseek/deepseek-v4-pro', 'openrouter:deepseek/deepseek-v4-flash', 'openrouter:deepseek/deepseek-v3.2'")

# Set to None for unlimited, or an integer to cap per-user calls
QUOTA_DEFAULT = 1200

# Upstream routing table: model-prefix -> upstream base URL
# Add new model families here without touching any other file
UPSTREAM_ROUTES = {
    "openrouter": "http://localhost:8018",
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
    "model": "gpt-5.1",
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
    model="gpt5",  # 'openrouter:openai/gpt-5.4-nano',''openrouter:openai/gpt-4o-mini','openrouter:deepseek/deepseek-v4-pro', 'openrouter:deepseek/deepseek-v4-flash', 'openrouter:deepseek/deepseek-v3.2'
    messages=[{"role": "user", "content": "Hello!"}]
)
print(response.choices[0].message.content)

# ====== 自己调用 ======
import requests

url = "http://api.apollodorus.xyz/v1/chat/completions"

headers = {
    "Authorization": "Bearer YOUR_API_KEY",
    "Content-Type": "application/json"
}

data = {
    "model": "gpt-4.1-mini",
    "messages": [
        {"role": "user", "content": "你好，简单介绍一下你自己"}
    ]
}

response = requests.post(url, headers=headers, json=data)

print(response.status_code)
print(response.json())
"""
