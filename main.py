"""
API Gateway - Main Entry Point
Auto-discovers and registers all plugins from the plugins/ directory.
Adding a new plugins: just create a new folder under plugins/ with router.py + config.py
"""
import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import importlib, pkgutil, os, sys

from core.ban import AutoBanMiddleware
from core.logger import setup_logging

sys.path.insert(0, os.path.dirname(__file__))

from core.database import engine, Base
from core.auth import router as auth_router
from core.admin import router as admin_router
from core.user import router as user_router


from contextlib import asynccontextmanager
from core.scheduler import start_scheduler

setup_logging()

@asynccontextmanager
async def lifespan(app: FastAPI):
    start_scheduler()
    yield


app = FastAPI(title="API Gateway", version="1.0.0",lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(AutoBanMiddleware)

# Core routers
app.include_router(auth_router, prefix="/api/auth", tags=["auth"])
app.include_router(admin_router, prefix="/api/admin", tags=["admin"])
app.include_router(user_router, prefix="/api/user", tags=["user"])

# ---- Plugin Auto-Discovery ----
PLUGINS_DIR = os.path.join(os.path.dirname(__file__), "plugins")

def load_plugins():
    for finder, name, ispkg in pkgutil.iter_modules([PLUGINS_DIR]):
        if not ispkg:
            continue
        try:
            module = importlib.import_module(f"plugins.{name}.router")
            if hasattr(module, "router"):
                prefix = getattr(module, "PLUGIN_PREFIX", f"/api/v1/{name}")
                app.include_router(module.router, prefix=prefix, tags=[name])
                print(f"[Plugin] Loaded: {name} -> {prefix}")
        except Exception as e:
            print(f"[Plugin] Failed to load {name}: {e}")

load_plugins()


@app.get("/api/health")
async def health():
    return {"status": "ok"}


@app.get("/api/plugins")
async def list_plugins():
    plugins = []
    for finder, name, ispkg in pkgutil.iter_modules([PLUGINS_DIR]):
        if not ispkg: continue
        try:
            cfg = importlib.import_module(f"plugins.{name}.config")
            plugins.append({
                "name": name,
                "display_name": getattr(cfg, "DISPLAY_NAME", name),
                "description": getattr(cfg, "DESCRIPTION", ""),
                "quota_default": getattr(cfg, "QUOTA_DEFAULT", None),
                "example": getattr(cfg, "EXAMPLE", ""),

                # ==== 增加这行 ====
                "post_test": getattr(cfg, "POST_TEST", None),
            })
        except Exception:
            pass
    return plugins

# ---- 托管前端静态文件 ----
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

FRONTEND_DIR = os.path.join(os.path.dirname(__file__), "frontend")
if os.path.exists(FRONTEND_DIR):
    app.mount("/static", StaticFiles(directory="frontend/static"), name="static")

    @app.get("/", include_in_schema=False)
    async def serve_index():
        return FileResponse(os.path.join(FRONTEND_DIR, "index.html"))
if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8080)