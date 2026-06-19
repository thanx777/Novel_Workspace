"""
Novel Forge — FastAPI application entry point.

Only app creation, middleware, router mounting, login endpoint and startup
event live here.  All business-logic endpoints have been moved to api/
sub-modules.
"""
import os
import logging

# ── Logging 配置（全局一次）──────────────────────────────────────────
os.makedirs('logs', exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('logs/novel_workspace.log', encoding='utf-8'),
    ]
)

from fastapi import FastAPI, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

# ── Auth ─────────────────────────────────────────────────────────────
from api.auth import require_auth, require_admin, create_access_token, verify_password, is_auth_disabled
from api.auth_models import LoginRequest, Token
from project_db import get_user_by_username, init_default_admin

# ── Shared limiter (single instance for all routers) ─────────────────
from api.shared import limiter

# ── Sub-routers ──────────────────────────────────────────────────────
from api.v2_router import router as v2_router
from api.v1_router import router as v1_router
from api.presets import router as presets_router
from api.skills import router as skills_router
from api.workspace import router as workspace_router
from api.agent_catalog import router as agent_catalog_router
from api.test_exec import router as test_exec_router
from api.assistant import router as assistant_router
from api.config_api import router as config_router
from api.v2_projects import router as v2_projects_router

# ============================================
# FastAPI App
# ============================================

app = FastAPI()

# Rate limiter
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


@app.on_event("startup")
async def _startup_init():
    """应用启动时初始化默认管理员账户"""
    init_default_admin()


# ============================================
# Auth — Login (kept in main.py)
# ============================================

@app.post("/api/auth/login", response_model=Token)
async def login(req: LoginRequest):
    """用户登录，返回 JWT token"""
    if is_auth_disabled():
        token = create_access_token(data={"sub": "dev", "role": "admin"})
        return Token(access_token=token)
    user = get_user_by_username(req.username)
    if not user or not verify_password(req.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    token = create_access_token(data={"sub": user["username"], "role": user["role"]})
    return Token(access_token=token)


# ============================================
# CORS
# ============================================

_DEFAULT_ALLOWED_ORIGINS = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:5174",
    "http://127.0.0.1:5174",
    "http://localhost:5176",
    "http://127.0.0.1:5176",
    "http://localhost:4173",
    "http://127.0.0.1:4173",
    "http://localhost:3000",
    "http://127.0.0.1:3000",
]


def _get_allowed_origins():
    """从环境变量 CORS_ORIGINS 读取允许的源（逗号分隔），默认使用本地开发源。"""
    env_origins = os.environ.get("CORS_ORIGINS", "").strip()
    if env_origins:
        origins = [o.strip() for o in env_origins.split(",") if o.strip()]
        if "*" in origins:
            logging.getLogger(__name__).warning("[SECURITY] CORS_ORIGINS=* 允许所有源跨域，仅建议开发环境使用")
        return origins
    return _DEFAULT_ALLOWED_ORIGINS


app.add_middleware(
    CORSMiddleware,
    allow_origins=_get_allowed_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(SlowAPIMiddleware)

# ============================================
# Router mounting
# ============================================

# v2 engine router (分层大纲 + 知识图谱 + 引擎)
app.include_router(v2_router)

# v2 project management (CRUD, presets, chapters, memory, stage, files)
app.include_router(v2_projects_router)

# v1 legacy project CRUD (@deprecated)
app.include_router(v1_router)

# Feature routers
app.include_router(presets_router)
app.include_router(skills_router)
app.include_router(workspace_router)
app.include_router(agent_catalog_router)
app.include_router(test_exec_router)
app.include_router(assistant_router)
app.include_router(config_router)

# ============================================
# Startup (uvicorn)
# ============================================

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
