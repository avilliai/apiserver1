"""
plugins/sd_proxy/config.py

Stable Diffusion Proxy 配置
"""

DISPLAY_NAME = "GPT IMAGE 2"
DESCRIPTION = "强大的图片编辑模型"

# 每个 API Key 每天 50 次
QUOTA_DEFAULT = 10

# 统一转发到你的 SD 服务
UPSTREAM_BASE_URL = "http://localhost:8009"

# 是否需要 API KEY（一般 SD WebUI 不需要，可以留空）
UPSTREAM_API_KEY = ""



EXAMPLE = """
暂不开放
"""