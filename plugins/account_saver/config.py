"""
plugins/openai_proxy/config.py

Plugin configuration. This file is the ONLY place you need to edit for this plugins.
- QUOTA_DEFAULT: None = unlimited; any int = calls per user before 429
- DISPLAY_NAME / DESCRIPTION: shown in frontend UI automatically
- DB_EXTRA_FIELDS: optional metadata (informational, not auto-migrated)
"""

DISPLAY_NAME = "account saver"
DESCRIPTION = "Unified OpenAI-compatible proxy. Routes Grok → :8000, GPT/Gemini/DeepSeek → :8001"

#转发到上游token管理器
TOKEN_MANAGER_URL="http://localhost:8080/admin/tokens/add"
TOKEN_MANAGER_KEY = "your-api-key-here"

# Set to None for unlimited, or an integer to cap per-user calls
QUOTA_DEFAULT = None

EXAMPLE = """
不向外开放
"""