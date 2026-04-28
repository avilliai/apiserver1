"""
plugins/openai_proxy_v2/config.py

Plugin configuration for the v2 proxy (api.apollodorus.xyz/v2).
All requests are forwarded to localhost:8007/v1.
- QUOTA_DEFAULT: None = unlimited; any int = calls per user per day before 429
"""

DISPLAY_NAME = "OpenAI Proxy v2 Models"
DESCRIPTION = (
    "v2 多模型代理，获取模型列表"
)

# Per-user daily quota (None = unlimited)

# Single upstream for all v2 models
UPSTREAM_BASE = "http://localhost:8007"

# Your master API key injected into every upstream request
UPSTREAM_API_KEY = "sdfa"




# DB_EXTRA_FIELDS: informational, tracked in RequestLog.extra_json
DB_EXTRA_FIELDS = ["model", "prompt_tokens", "completion_tokens"]

POST_TEST = {
    "headers": {"Authorization": "Bearer apikey"},
    "type": "get",
    "end_point": "/v2/models",
    "params": {
    },
}

EXAMPLE = """

"""