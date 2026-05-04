"""
plugins/openai_proxy_v2/config.py

Plugin configuration for the v2 proxy (api.apollodorus.xyz/v2).
All requests are forwarded to localhost:8007/v1.
- QUOTA_DEFAULT: None = unlimited; any int = calls per user per day before 429
"""

DISPLAY_NAME = "OpenAI Proxy v0"
DESCRIPTION = (
    "gemini-3-flash-preview专用接口，配额独立"
)

# Per-user daily quota (None = unlimited)
QUOTA_DEFAULT = 3000

# Single upstream for all v2 models
UPSTREAM_BASE = "http://localhost:8006"

# Your master API key injected into every upstream request
UPSTREAM_API_KEY = "sdfa"

# All supported models on this upstream
SUPPORTED_MODELS = [
    "gemini-3-flash-preview",
]

# DB_EXTRA_FIELDS: informational, tracked in RequestLog.extra_json
DB_EXTRA_FIELDS = ["model", "prompt_tokens", "completion_tokens"]

POST_TEST = {
    "headers": {"Authorization": "Bearer apikey"},
    "type": "post",
    "end_point": "/v0/chat/completions",
    "params": {
        "model": "gemini-3-flash-preview",
        "messages": [
            {"role": "user", "content": "你好，简单介绍一下你自己"}
        ],
    },
}

EXAMPLE = """
from openai import OpenAI

client = OpenAI(
    base_url="http://api.apollodorus.xyz/v0",
    api_key="sk-xxxx"
)

response = client.chat.completions.create(
    model="gemini-3-flash-preview",
    messages=[{"role": "user", "content": "Hello!"}]
)
print(response.choices[0].message.content)
"""
