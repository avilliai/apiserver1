"""
plugins/openai_proxy_v2/config.py

Plugin configuration for the v2 proxy (api.apollodorus.xyz/v2).
All requests are forwarded to localhost:8007/v1.
- QUOTA_DEFAULT: None = unlimited; any int = calls per user per day before 429
"""

DISPLAY_NAME = "OpenAI Proxy v2"
DESCRIPTION = (
    "v2 多模型代理，支持模型：alibaba/qwen3.x, anthropic/claude-*, google/gemini-3.x, "
    "openai/gpt-5.x, xai/grok-4.20, mistral/*, deepseek/v4, 及更多"
)

# Per-user daily quota (None = unlimited)
QUOTA_DEFAULT = 100

# Single upstream for all v2 models
UPSTREAM_BASE = "http://localhost:8007"

# Your master API key injected into every upstream request
UPSTREAM_API_KEY = "sdfa"

# All supported models on this upstream
SUPPORTED_MODELS = [
    "alibaba/qwen3.5-122b-a10b",
    "alibaba/qwen3.5-397b-a17b",
    "alibaba/qwen3.6-27b",
    "alibaba/qwen3.6-35b-a3b",
    "alibaba/qwen3.6-flash",
    "alibaba/qwen3.6-max",
    "alibaba/qwen3.6-plus",
    "amazon/nova-2-lite",
    "anthropic/claude-4.5-haiku",
    "anthropic/claude-opus-4.7",
    "anthropic/claude-sonnet-4.6",
    "arcee/trinity-large-thinking",
    "cohere/command-a-reasoning",
    "cohere/command-a-vision",
    "deepseek/deepseek-v4-flash",
    "deepseek/deepseek-v4-pro",
    "google/gemini-3-flash",
    "google/gemini-3-pro-image",
    "google/gemini-3.1-pro-preview",
    "google/gemini-3.1-flash-image",
    "google/gemini-3.1-flash-lite",
    "google/gemma-4-31b-it",
    "google/gemma-4-26b-a4b-it",
    "minimax/minimax-m2.7",
    "minimax/minimax-m2.7-highspeed",
    "mistral/codestral",
    "mistral/magistral-medium",
    "mistral/magistral-small",
    "mistral/mistral-large",
    "mistral/mistral-medium",
    "mistral/mistral-small-4-119b",
    "mistral/pixtral-large",
    "moonshotai/kimi-k2.6",
    "nvidia/nemotron-3-super-120b-a12b",
    "openai/gpt-5.4-mini",
    "openai/gpt-5.4-nano",
    "openai/gpt-5.5",
    "openai/gpt-5.5-pro",
    "openai/gpt-5.3-codex",
    "openai/gpt-oss-120b",
    "stepfun/step-3.5-flash",
    "xai/grok-4.20-multi-agent",
    "xai/grok-4.20-non-reasoning",
    "xai/grok-4.20-reasoning",
    "xai/grok-code-fast-1",
    "xiaomi/mimo-v2-flash",
    "xiaomi/mimo-v2.5",
    "xiaomi/mimo-v2.5-pro",
    "zai/glm-4.7-flash",
    "zai/glm-5-turbo",
    "zai/glm-5.1",
    "zai/glm-5v-turbo",
]

# DB_EXTRA_FIELDS: informational, tracked in RequestLog.extra_json
DB_EXTRA_FIELDS = ["model", "prompt_tokens", "completion_tokens"]

POST_TEST = {
    "headers": {"Authorization": "Bearer apikey"},
    "type": "post",
    "end_point": "/v2/chat/completions",
    "params": {
        "model": "google/gemini-3-flash",
        "messages": [
            {"role": "user", "content": "你好，简单介绍一下你自己"}
        ],
    },
}

EXAMPLE = """
from openai import OpenAI

client = OpenAI(
    base_url="http://api.apollodorus.xyz/v2",
    api_key="sk-xxxx"
)

response = client.chat.completions.create(
    model="anthropic/claude-sonnet-4.6",
    messages=[{"role": "user", "content": "Hello!"}]
)
print(response.choices[0].message.content)
"""
