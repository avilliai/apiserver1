"""
plugins/openai_proxy_v3/config.py

Plugin configuration for the v3 proxy (Pegasus / localhost:8011).
All models are namespaced with "Pegasus/" prefix in this system to avoid
collision with v1 models that share the same bare names.

When forwarding to 8011, the prefix is stripped so the upstream receives
the exact model name it expects (e.g. "gemini-pro", not "Pegasus/gemini-pro").

- QUOTA_DEFAULT: None = unlimited; any int = calls per user before 429
"""

DISPLAY_NAME = "OpenAI Proxy v3 (Pegasus)"
DESCRIPTION = (
    "Pegasus 多模型代理，支持模型（调用时加 Pegasus/ 前缀）："
    "Pegasus/gemini-pro, Pegasus/gemini-flash, Pegasus/claude-sonnet, "
    "Pegasus/claude-opus, Pegasus/gemini-2.5-pro, Pegasus/gpt-5"
)

# Per-user quota (None = unlimited)
QUOTA_DEFAULT = 200

# Single upstream for all v3 models
UPSTREAM_BASE = "http://localhost:8011"

# Master API key injected into every upstream request
UPSTREAM_API_KEY = ""

# Prefix used to namespace Pegasus models in this system.
# All external-facing model IDs carry this prefix; it is stripped before forwarding.
MODEL_PREFIX = "Pegasus/"

# Bare model names as accepted by the upstream (8011).
# The external ID seen by API consumers is MODEL_PREFIX + bare_name.
_BARE_MODELS: list[str] = [
    "gemini-pro",
    "gemini-flash",
    "claude-sonnet",   # actually claude-sonnet-4.6
    "claude-opus",     # actually claude-opus-4.7
    "gemini-2.5-pro",
    "gpt-5",           # actually gpt-5.4
]

# Full prefixed names exposed to API consumers (and used for set-membership checks)
SUPPORTED_MODELS: list[str] = [MODEL_PREFIX + m for m in _BARE_MODELS]

# DB_EXTRA_FIELDS: informational, tracked in RequestLog.extra_json
DB_EXTRA_FIELDS = ["model", "prompt_tokens", "completion_tokens"]

POST_TEST = {
    "headers": {"Authorization": "Bearer apikey"},
    "type": "post",
    "end_point": "/v3/chat/completions",
    "params": {
        "model": "Pegasus/gemini-pro",

        "messages": [
            {"role": "user", "content": "你好，简单介绍一下你自己"}
        ],
    },
}

EXAMPLE = """
from openai import OpenAI

client = OpenAI(
    base_url="http://api.apollodorus.xyz/v3",
    api_key="sk-xxxx"
)
# 可用模型Pegasus/gemini-flash，Pegasus/claude-sonnet，Pegasus/claude-opus，Pegasus/gemini-2.5-pro，Pegasus/gpt-5

# 使用 v3 专属端点
response = client.chat.completions.create(
    model="Pegasus/claude-sonnet",
    messages=[{"role": "user", "content": "Hello!"}]
)
print(response.choices[0].message.content)

# 也可以通过 v1 端点调用（配额独立计入 openai_proxy_v3）
client_v1 = OpenAI(
    base_url="http://api.apollodorus.xyz/v1",
    api_key="sk-xxxx"
)
response = client_v1.chat.completions.create(
    model="Pegasus/claude-sonnet",
    messages=[{"role": "user", "content": "Hello!"}]
)
print(response.choices[0].message.content)
"""