"""
plugins/openai_proxy/config.py

Plugin configuration. This file is the ONLY place you need to edit for this plugins.
- QUOTA_DEFAULT: None = unlimited; any int = calls per user before 429
- DISPLAY_NAME / DESCRIPTION: shown in frontend UI automatically
- DB_EXTRA_FIELDS: optional metadata (informational, not auto-migrated)
"""

DISPLAY_NAME = "AI Proxy"
DESCRIPTION = "Unified OpenAI-compatible proxy. Routes Grok → :8000, GPT/Gemini/DeepSeek → :8001"

# Set to None for unlimited, or an integer to cap per-user calls
QUOTA_DEFAULT = 3000

# Upstream routing table: model-prefix -> upstream base URL
# Add new model families here without touching any other file
UPSTREAM_ROUTES = {
    "grok":     "http://localhost:8000",
    "gpt":      "http://localhost:8001",
    "gemini":   "http://localhost:8001",
    "deepseek": "http://localhost:8001",
    "o1":       "http://localhost:8001",
    "o3":       "http://localhost:8001",
}

# Your master API key injected into every upstream request
UPSTREAM_API_KEY = ""

# DB_EXTRA_FIELDS: informational, tracked in RequestLog.extra_json
DB_EXTRA_FIELDS = ["model", "prompt_tokens", "completion_tokens"]

EXAMPLE = """
from openai import OpenAI

client = OpenAI(
    base_url="http://apollodorus.xyz:8080/v1",
    api_key="sk-xxxx"
)

# Chat completion
response = client.chat.completions.create(
    model="grok-4",  # 有其他模型，很多，懒得写，自己试去吧
    messages=[{"role": "user", "content": "Hello!"}]
)
print(response.choices[0].message.content)
"""