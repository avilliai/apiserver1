# API Gateway

高拓展性的api管理系统        
**由于本人是前端苦手，故本项目首要目标是让开发者尽量避开前端工作。在增加新功能后，仅需在后端插件的config.py中稍作配置，前端即可自动更新**。

<img width="2546" height="1394" alt="image" src="https://github.com/user-attachments/assets/88238b42-7d36-417c-85bc-005e8af99499" />

---

## 快速启动

```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 创建首个管理员（一次性）
python create_admin.py --username admin --password yourpassword

# 3. 启动后端
python -m uvicorn main:app --host 0.0.0.0 --port 8080
或  
python -m uvicorn main:app --host 0.0.0.0 --port 8080 --reload # 开发环境，代码修改自动热重载

# 4. 前端
# 直接用浏览器打开 localhost:8080
```

---

## 目录结构
`项目自带openai router，可转发openai格式请求到多个不同的上游服务。`     
```
api-gateway/
├── main.py                 # 入口，自动发现插件
├── core/
│   ├── database.py         # 数据模型 (User, InviteCode, RequestLog)
│   ├── auth.py             # 注册/登录
│   ├── auth_utils.py       # JWT / 密码工具
│   ├── quota.py            # 配额检查依赖 (require_quota)
│   ├── admin.py            # 管理员接口
│   ├── scheduler.py        # 定时刷新配额
│   └── user.py             # 用户自助接口
└── plugins/
│   └── openai_proxy/       # 第一个插件
│       ├── __init__.py
│       ├── config.py       # 插件配置（唯一需要改的文件）
│       └── router.py       # FastAPI 路由
├── frontend/
│   └── index.html              # 单文件前端
└── create_admin.py         # 初始管理员创建脚本
```

---

## 如何添加新插件

**只需在 `plugins/` 下新建文件夹，包含三个文件：**

### 1. `__init__.py`（空文件）

```python
# my_plugin package
```

### 2. `config.py`

```python
DISPLAY_NAME = "My Plugin"          # 前端显示名称
DESCRIPTION = "Do something cool" # 描述

# None = 不限制；整数 = 每用户每日调用上限
QUOTA_DEFAULT = 100

# 可选：供router内引用的其他配置
MY_SETTING1 = "value"
MY_SETTING2 = [1, 2, 3]

#EXAMPLE是可选的，自动在前端显示调用示例
EXAMPLE = """
import base64
import requests
BASE = "http://apollodorus.xyz:8080"
apikey='sk-xxxx'
r= requests.post(
    BASE + "/action",  # 注意这里的路径
    headers={"Authorization":f"Bearer {apikey}"},
    timeout=1000)
print(r.json())
"""

```

### 3. `router.py`

```python
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from core.database import get_db, User
from core.quota import get_current_user, require_quota, log_request
from plugins.my_plugin import config

#PLUGIN_PREFIX = "/api/v1/my_plugin"  # 挂载路径。此时需要请求http://localhost:8080/api/v1/my_plugin/action
PLUGIN_PREFIX = ""  # 设置为""，此时请求http://localhost:8080/action
PLUGIN_NAME = "my_plugin"  # 插件文件夹名，必须一致。
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

也可使用管理员账户密码，将邀请码生成封装为函数。
```python
import httpx


def generate_invites(base_url, username, password, count=1):
    """
    自动登录 + 生成邀请码

    :param base_url: 例如 http://localhost:8080
    :param username: 管理员用户名
    :param password: 管理员密码
    :param count: 生成数量
    :return: 邀请码列表
    """

    base_url = base_url.rstrip("/")
    with httpx.Client(timeout=10) as client:
        login_resp = client.post(
            f"{base_url}/api/auth/login",
            json={
                "username": username,
                "password": password
            }
        )
        if login_resp.status_code != 200:
            raise Exception(f"登录失败: {login_resp.text}")
        token = login_resp.json().get("access_token")
        if not token:
            raise Exception("没有拿到 token")
        # 2️⃣ 生成邀请码
        gen_resp = client.post(
            f"{base_url}/api/admin/invite/generate",
            params={"count": count},
            headers={
                "Authorization": f"Bearer {token}"
            }
        )
        if gen_resp.status_code != 200:
            raise Exception(f"生成失败: {gen_resp.text}")

        data = gen_resp.json()
        return data.get("codes", [])
codes = generate_invites(
    base_url="http://localhost:8080",  #真到生产环境了记得自己改
    username="admin_name",  #你自己的管理员账户和密码
    password="pwd",
    count=1  #生成数量
)

print(codes)
```

---

## OpenAI 代理插件配置

编辑 `plugins/openai_proxy/config.py`：

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
    base_url="http://your-gateway/v1",
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
