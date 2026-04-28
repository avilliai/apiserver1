"""
plugins/openai_proxy_v2/config.py

OpenAI Proxy V2 Configuration.
"""

DISPLAY_NAME = "OpenAI Proxy V2"

DESCRIPTION = (
    "V2 代理节点。可用模型：\n"
    "alibaba/qwen3.5-122b-a10b, alibaba/qwen3.5-397b-a17b, alibaba/qwen3.6-27b, alibaba/qwen3.6-35b-a3b, alibaba/qwen3.6-flash, alibaba/qwen3.6-max, alibaba/qwen3.6-plus, "
    "amazon/nova-2-lite, "
    "anthropic/claude-4.5-haiku, anthropic/claude-opus-4.7, anthropic/claude-sonnet-4.6, "
    "arcee/trinity-large-thinking, "
    "cohere/command-a-reasoning, cohere/command-a-vision, "
    "deepseek/deepseek-v4-flash, deepseek/deepseek-v4-pro, "
    "google/gemini-3-flash, google/gemini-3-pro-image, google/gemini-3.1-pro-preview, google/gemini-3.1-flash-image, google/gemini-3.1-flash-lite, "
    "google/gemma-4-31b-it, google/gemma-4-26b-a4b-it, "
    "minimax/minimax-m2.7, minimax/minimax-m2.7-highspeed, "
    "mistral/codestral, mistral/magistral-medium, mistral/magistral-small, mistral/mistral-large, mistral/mistral-medium, mistral/mistral-small-4-119b, mistral/pixtral-large, "
    "moonshotai/kimi-k2.6, "
    "nvidia/nemotron-3-super-120b-a12b, "
    "openai/gpt-5.4-mini, openai/gpt-5.4-nano, openai/gpt-5.5, openai/gpt-5.5-pro, openai/gpt-5.3-codex, openai/gpt-oss-120b, "
    "stepfun/step-3.5-flash, "
    "xai/grok-4.20-multi-agent, xai/grok-4.20-non-reasoning, xai/grok-4.20-reasoning, xai/grok-code-fast-1, "
    "xiaomi/mimo-v2-flash, xiaomi/mimo-v2.5, xiaomi/mimo-v2.5-pro, "
    "zai/glm-4.7-flash, zai/glm-5-turbo, zai/glm-5.1, zai/glm-5v-turbo"
)

# 每日配额限制为 1500
QUOTA_DEFAULT = 1000

# 统一上游接口地址
UPSTREAM_URL = "http://localhost:8007/v1"

# 你的 V2 上游请求 API KEY
UPSTREAM_API_KEY = ""

# 数据库记录扩展字段
DB_EXTRA_FIELDS = ["model", "prompt_tokens", "completion_tokens"]

POST_TEST = {
    "headers": {"Authorization": f"Bearer apikey"},
    "type": "post",
    "end_point": "/v2/chat/completions",
    "params": {
        "model": "openai/gpt-5.5",
        "messages":[
            {"role": "user", "content": "你好，简单介绍一下你自己"}
        ]
    }
}

EXAMPLE = """
from openai import OpenAI

client = OpenAI(
    base_url="https://api.apollodorus.xyz/v2",
    api_key="sk-xxxx"
)

# Chat completion
response = client.chat.completions.create(
    model="openai/gpt-5.5",
    messages=[{"role": "user", "content": "Hello!"}]
)
print(response.choices[0].message.content)
"""