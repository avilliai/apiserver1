# API Gateway

邀请码制 API 网关，支持插件化接口、配额管理、管理员控制台。

---

## 快速启动

```bash
# 1. 安装依赖
cd backend
pip install -r requirements.txt

# 2. 创建首个管理员（一次性）
python create_admin.py --username admin --password yourpassword

# 3. 启动后端
uvicorn main:app --reload --port 8080

# 4. 前端
# 直接用浏览器打开 frontend/index.html，或用 nginx/caddy 托管
# 开发时设置 index.html 顶部 const API = 'http://localhost:8080'
```

---

## 目录结构

```
api-gateway/
├── backend/
│   ├── main.py                 # 入口，自动发现插件
│   ├── core/
│   │   ├── database.py         # 数据模型 (User, InviteCode, RequestLog)
│   │   ├── auth.py             # 注册/登录
│   │   ├── auth_utils.py       # JWT / 密码工具
│   │   ├── quota.py            # 配额检查依赖 (require_quota)
│   │   ├── admin.py            # 管理员接口
│   │   └── user.py             # 用户自助接口
│   └── plugins/
│       └── openai_proxy/       # 第一个插件
│           ├── __init__.py
│           ├── config.py       # 插件配置（唯一需要改的文件）
│           └── router.py       # FastAPI 路由
├── frontend/
│   └── index.html              # 单文件前端
└── scripts/
    └── create_admin.py         # 初始管理员创建脚本
```

---

## 如何添加新插件

**只需在 `backend/plugins/` 下新建文件夹，包含三个文件：**

### 1. `__init__.py`（空文件）

```python
# my_plugin package
```

### 2. `config.py`

```python
DISPLAY_NAME = "My Plugin"          # 前端显示名称
DESCRIPTION = "Does something cool" # 描述

# None = 不限制；整数 = 每用户调用上限
QUOTA_DEFAULT = 100

# 可选：供路由内引用的其他配置
MY_SETTING = "value"
```

### 3. `router.py`

```python
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from core.database import get_db, User
from core.quota import get_current_user, require_quota, log_request
from plugins.my_plugin import config

PLUGIN_PREFIX = "/api/v1/my_plugin"  # 挂载路径
PLUGIN_NAME = "my_plugin"
router = APIRouter()

@router.post("/action")
async def my_action(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _quota=Depends(require_quota(PLUGIN_NAME)),
):
    # 业务逻辑
    await log_request(db, user, PLUGIN_NAME, "/action", 200)
    return {"result": "ok"}
```

**重启后端即可**。无需改动任何其他文件，包括前端。

---

## 配额系统说明

- 配额以 JSON 存储在 `users.quota_json`，格式：
  ```json
  {
    "openai_proxy": {"used": 42, "limit": 500},
    "my_plugin":    {"used": 0,  "limit": null}
  }
  ```
- `limit: null` = 不限制
- **老用户兼容**：登录时自动检测新插件并补充默认配额，无需数据库迁移
- 新用户注册时自动扫描所有插件分配默认配额

---

## 邀请码流程

1. 管理员登录后台 → Invite Codes → 生成
2. 将 code 发给用户
3. 用户注册时填写，注册成功后 code 立即销毁（不可复用）

---

## OpenAI 代理插件配置

编辑 `backend/plugins/openai_proxy/config.py`：

```python
UPSTREAM_API_KEY = "sk-your-real-key"  # 你的主 API Key

UPSTREAM_ROUTES = {
    "grok":     "http://localhost:8000",  # Grok 转发目标
    "gpt":      "http://localhost:8001",  # GPT/Gemini/DeepSeek 转发目标
    "gemini":   "http://localhost:8001",
    "deepseek": "http://localhost:8001",
}

QUOTA_DEFAULT = 500  # 每用户默认 500 次
```

客户端调用方式（完全兼容 OpenAI SDK）：

```python
from openai import OpenAI

client = OpenAI(
    base_url="http://your-gateway/api/v1/openai",
    api_key="your-gateway-user-token",  # 用登录返回的 JWT
)

resp = client.chat.completions.create(
    model="gpt-4o",
    messages=[{"role": "user", "content": "Hello"}]
)
```

---

## 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `SECRET_KEY` | `change-me-in-production-please` | JWT 签名密钥，生产必须修改 |
| `DATABASE_URL` | SQLite `gateway.db` | 可换 PostgreSQL |
