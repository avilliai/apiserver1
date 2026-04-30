"""
plugins/openai_proxy_v2/config.py

Plugin configuration for the v2 proxy (api.apollodorus.xyz/v2).
All requests are forwarded to localhost:8007/v1.
- QUOTA_DEFAULT: None = unlimited; any int = calls per user per day before 429
"""

DISPLAY_NAME = "OpenAI Proxy Models"
DESCRIPTION = (
    "v1 多模型代理，获取模型列表"
)



# Your master API key injected into every upstream request
UPSTREAM_API_KEY = ""


POST_TEST = {
    "headers": {"Authorization": "Bearer apikey"},
    "type": "get",
    "end_point": "/v1/models",
    "params": {
    },
}

EXAMPLE = """

"""