# -*- mode: python ; coding: utf-8 -*-
"""Novel Workspace PyInstaller spec — onefile 打包配置"""

import os
import sys

block_cipher = None

# 前端构建产物路径
frontend_dist = os.path.join(SPECPATH, 'frontend', 'dist')

a = Analysis(
    ['backend/launcher.py'],
    pathex=['backend'],
    binaries=[],
    datas=[
        # 前端静态资源（SPA）
        (frontend_dist, 'frontend/dist'),
    ],
    hiddenimports=[
        # uvicorn 动态导入
        'uvicorn.logging',
        'uvicorn.protocols.websockets.auto',
        'uvicorn.protocols.http.auto',
        'uvicorn.lifespan.on',
        'uvicorn.protocols.http.httptools_impl',
        'uvicorn.protocols.http.h11_impl',
        'uvicorn.protocols.websockets.websockets_impl',
        'uvicorn.protocols.websockets.wsproto_impl',
        # FastAPI / pydantic
        'pydantic',
        'email_validator',
        # 项目依赖
        'slowapi',
        'sse_starlette',
        'cryptography',
        'cryptography.fernet',
        'jose',
        'passlib',
        'passlib.handlers',
        'passlib.handlers.bcrypt',
        # pywebview
        'webview',
        'webview.platforms',
        'webview.platforms.winforms',
        # 项目模块
        'paths',
        'project_db',
        'knowledge_graph',
        'engines',
        'engines.common',
        'engines.common.base_engine',
        'engines.common.llm_client',
        'engines.common.kg_adapter',
        'engines.common.genre_adapter',
        'engines.common.hallucination_guard',
        'engines.common.prompts',
        'engines.common.state',
        'engines.outline',
        'engines.outline.engine',
        'engines.writing',
        'engines.writing.engine',
        'engines.review',
        'engines.review.engine',
        'genre_data',
        'genre_data.writing_guides',
        'genre_data.inkos_data',
        'genre_data.genre_profiles',
        'genre_data.taxonomy',
        'genre_data.detect',
        # API 路由
        'api',
        'api.shared',
        'api.auth',
        'api.auth_models',
        'api.v2_router',
        'api.v1_router',
        'api.presets',
        'api.skills',
        'api.workspace',
        'api.agent_catalog',
        'api.assistant',
        'api.config_api',
        'api.v2_projects',
        'api.skill_loader',
        'api.engine_registry',
    ],
    excludes=[
        'pytest', 'playwright', 'IPython', 'matplotlib',
        'tkinter', 'scipy', 'numpy', 'pandas',
        'test_runner', 'api.test_exec',
    ],
    noarchive=False,
)
pyz = PYZ(a.pure, cipher=block_cipher)
exe = EXE(
    pyz, a.scripts, a.binaries, a.datas,
    name='NovelWorkspace',
    console=False,
    icon=os.path.join(SPECPATH, 'build', 'IMG_20260620_000506.ico'),
    onefile=True,
)
