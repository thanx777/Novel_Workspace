"""
Novel Forge — FastAPI application entry point.
Imports the execution engine from executor.py and exposes API routes.
"""
import asyncio
import json
import os
import re
import time
from fastapi import FastAPI, HTTPException, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from sse_starlette.sse import EventSourceResponse
from pydantic import BaseModel
from typing import List, Optional, Dict, Any, Tuple

# LLM client (migrated from executor.py)
from engines.common.llm_client import AgentConfig, call_llm, is_llm_error

# Workspace & file utilities — 同步 project_db 的路径定义
from project_db import WORKSPACE_DIR as _PDB_WS, PROJECTS_DIR as _PDB_PJ
WORKSPACE_DIR = _PDB_WS
PROJECTS_DIR = _PDB_PJ

def _resolve_workspace_dir(path: str, default_name: str) -> str:
    """Resolve workspace/projects directory path."""
    if path and path.strip():
        return os.path.abspath(path.strip())
    return os.path.abspath(os.path.join(os.path.dirname(__file__), default_name))

def get_full_path(filename: str) -> str:
    """Get full path for a workspace file, with path traversal protection."""
    full = os.path.abspath(os.path.join(WORKSPACE_DIR, filename))
    if not full.startswith(os.path.abspath(WORKSPACE_DIR)):
        raise HTTPException(status_code=400, detail="Invalid path")
    return full

def safe_join(root: str, *paths: str) -> str:
    """安全拼接路径，防止路径穿越。返回的绝对路径必须在 root 内。"""
    root_abs = os.path.abspath(root)
    full = os.path.abspath(os.path.join(root_abs, *paths))
    if not full.startswith(root_abs + os.sep) and full != root_abs:
        raise HTTPException(status_code=400, detail="Invalid path")
    return full

class FileContent(BaseModel):
    content: str

class WorkspaceConfig(BaseModel):
    path: str
from test_runner import parse_test_instructions, execute_test, terminal_executor_stream, is_dangerous, execute_terminal_force

# V2 API Router（分层大纲 + 知识图谱）
v2_router = None
try:
    from v2_api import router as _v2_router
    v2_router = _v2_router
except Exception as _v2_err:
    print(f"[warn] v2_api 加载失败: {_v2_err}")

# ============================================
# WebSocket Terminal Manager
# ============================================

class TerminalManager:
    _connections: set = set()

    @classmethod
    def connect(cls, ws):
        cls._connections.add(ws)

    @classmethod
    def disconnect(cls, ws):
        cls._connections.discard(ws)

    @classmethod
    async def broadcast(cls, data: dict):
        dead = set()
        for ws in cls._connections:
            try:
                await ws.send_json(data)
            except Exception:
                dead.add(ws)
        cls._connections -= dead

    @classmethod
    def count(cls) -> int:
        return len(cls._connections)

# ============================================
# FastAPI App
# ============================================

app = FastAPI()

# CORS 白名单：仅允许本地开发前端访问，避免任意源跨域
_ALLOWED_ORIGINS = [
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

app.add_middleware(
    CORSMiddleware,
    allow_origins=_ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 挂载 v2 router
if v2_router is not None:
    app.include_router(v2_router)
    print(f"[info] v2_api router 已挂载（分层大纲 + 知识图谱）routes={len(v2_router.routes)}")
else:
    print("[warn] v2_api router 为 None，未挂载")

# ============================================
# Config helpers
# ============================================

def _get_config_path():
    return os.path.join(os.path.dirname(__file__), "config.json")

def _read_config():
    path = _get_config_path()
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"presets": []}

def _write_config(data):
    with open(_get_config_path(), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

# ============================================
# API — Presets
# ============================================

class PresetCreate(BaseModel):
    name: str
    base_url: str
    model: str
    api_key: str
    api_format: str = "openai"
    thinking_mode: Optional[str] = None

class PresetUpdate(BaseModel):
    original_name: str
    name: str
    base_url: str
    model: str
    api_key: str
    api_format: str = "openai"
    thinking_mode: Optional[str] = None

@app.get("/api/presets")
def get_presets():
    config_path = os.path.join(os.path.dirname(__file__), "config.json")
    if os.path.exists(config_path):
        with open(config_path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"presets": []}

@app.post("/api/presets")
def add_preset(preset: PresetCreate):
    data = _read_config()
    if "presets" not in data:
        data["presets"] = []
    data["presets"].append(preset.model_dump())
    _write_config(data)
    return data

@app.delete("/api/presets")
def delete_preset(name: str):
    data = _read_config()
    if "presets" not in data:
        data["presets"] = []
    data["presets"] = [p for p in data["presets"] if p.get("name") != name]
    _write_config(data)
    return data

@app.put("/api/presets")
def update_preset(preset: PresetUpdate):
    data = _read_config()
    if "presets" not in data:
        data["presets"] = []
    for i, p in enumerate(data["presets"]):
        if p.get("name") == preset.original_name:
            data["presets"][i] = preset.model_dump(exclude={"original_name"})
            _write_config(data)
            return data
    raise HTTPException(status_code=404, detail="Preset not found")

@app.put("/api/presets/default")
def set_default_preset(name: str):
    """设置默认预设（新项目自动使用此预设）。"""
    data = _read_config()
    # 验证预设存在
    found = any(p.get("name") == name for p in data.get("presets", []))
    if not found:
        raise HTTPException(status_code=404, detail="Preset not found")
    data["default_preset"] = name
    _write_config(data)
    return data

@app.delete("/api/presets/default")
def clear_default_preset():
    """清除默认预设。"""
    data = _read_config()
    data.pop("default_preset", None)
    _write_config(data)
    return data

# ============================================
# API — Workspace Config
# ============================================

class WorkspaceConfigModel(BaseModel):
    workspace_dir: str = ""
    projects_dir: str = ""

@app.get("/api/workspace-config")
def get_workspace_config():
    data = _read_config()
    return {
        "workspace_dir": data.get("workspace_dir", ""),
        "projects_dir": data.get("projects_dir", ""),
        "current_workspace": WORKSPACE_DIR,
        "current_projects": PROJECTS_DIR,
        "default_workspace": os.path.abspath(os.path.join(os.path.dirname(__file__), "workspace")),
        "default_projects": os.path.abspath(os.path.join(os.path.dirname(__file__), "projects"))
    }

@app.put("/api/workspace-config")
def update_workspace_config(cfg: WorkspaceConfigModel):
    global WORKSPACE_DIR, PROJECTS_DIR
    data = _read_config()

    new_ws = cfg.workspace_dir.strip() if cfg.workspace_dir else ""
    new_pj = cfg.projects_dir.strip() if cfg.projects_dir else ""

    if new_ws:
        try:
            os.makedirs(new_ws, exist_ok=True)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Cannot create workspace dir: {str(e)}")
    if new_pj:
        try:
            os.makedirs(new_pj, exist_ok=True)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Cannot create projects dir: {str(e)}")

    data["workspace_dir"] = new_ws
    data["projects_dir"] = new_pj
    _write_config(data)

    WORKSPACE_DIR = _resolve_workspace_dir(new_ws, "workspace")
    PROJECTS_DIR = _resolve_workspace_dir(new_pj, "projects")

    return {
        "status": "success",
        "workspace_dir": WORKSPACE_DIR,
        "projects_dir": PROJECTS_DIR,
    }

@app.get("/api/workspace/config")
def get_workspace():
    return WorkspaceConfig(path=WORKSPACE_DIR)

@app.post("/api/workspace/config")
def set_workspace(config: WorkspaceConfig):
    global WORKSPACE_DIR
    WORKSPACE_DIR = config.path
    os.makedirs(WORKSPACE_DIR, exist_ok=True)
    return {"status": "success"}

# ============================================
# API — Files
# ============================================

class FolderStructure(BaseModel):
    folders: List[str]

@app.get("/api/workspace/files")
def list_files(folder: str = ""):
    target_dir = safe_join(WORKSPACE_DIR, folder) if folder else os.path.abspath(WORKSPACE_DIR)
    if not os.path.isdir(target_dir):
        return {"files": [], "folder": folder}
    files = []
    for f in sorted(os.listdir(target_dir)):
        full = os.path.join(target_dir, f)
        if os.path.isfile(full):
            files.append(f)
    return {"files": files, "folder": folder}

@app.post("/api/workspace/folders")
def create_folders(structure: FolderStructure):
    for folder in structure.folders:
        target = safe_join(WORKSPACE_DIR, folder)
        os.makedirs(target, exist_ok=True)
    return {"status": "success"}

@app.get("/api/workspace/files/{filename:path}")
def get_file(filename: str):
    path = get_full_path(filename)
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="File not found")
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        return {"content": f.read(), "filename": filename}

@app.post("/api/workspace/files/{filename:path}")
def save_file(filename: str, body: FileContent):
    path = get_full_path(filename)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(body.content)
    return {"status": "success", "filename": filename}

@app.delete("/api/workspace/files/{filename:path}")
def delete_file(filename: str):
    path = get_full_path(filename)
    if os.path.exists(path):
        os.remove(path)
        return {"status": "success"}
    raise HTTPException(status_code=404, detail="File not found")

# ============================================
# API — Projects
# ============================================

@app.get("/api/projects")
def list_projects():
    projects = []
    if os.path.isdir(PROJECTS_DIR):
        for f in sorted(os.listdir(PROJECTS_DIR)):
            if f.endswith(".json"):
                projects.append({"filename": f, "name": f.replace(".json", "")})
    return {"projects": projects}

@app.post("/api/projects")
def save_project(project: dict):
    name = project.get("name", "untitled")
    filename = re.sub(r'[<>:"/\\|?*]', "_", name) + ".json"
    path = os.path.join(PROJECTS_DIR, filename)
    os.makedirs(PROJECTS_DIR, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(project, f, ensure_ascii=False, indent=2)
    return {"status": "success", "filename": filename}

@app.get("/api/projects/{filename}")
def load_project(filename: str):
    if ".." in filename or "/" in filename or "\\" in filename:
        raise HTTPException(status_code=400, detail="Invalid filename")
    filepath = os.path.join(PROJECTS_DIR, filename)
    if not os.path.exists(filepath):
        raise HTTPException(status_code=404, detail="Project not found")
    with open(filepath, "r", encoding="utf-8") as f:
        return json.load(f)

@app.delete("/api/projects/{filename}")
def delete_project(filename: str):
    if ".." in filename or "/" in filename or "\\" in filename:
        raise HTTPException(status_code=400, detail="Invalid filename")
    filepath = os.path.join(PROJECTS_DIR, filename)
    if os.path.exists(filepath):
        os.remove(filepath)
        return {"status": "success"}
    raise HTTPException(status_code=404, detail="Project not found")

# ============================================
# API — Prompt Templates & Agent Catalog
# ============================================

@app.get("/api/prompt-templates")
def get_prompt_templates():
    """提示词模板列表（已迁移到新引擎，此端点保留兼容）。"""
    return {"frameworks": {}}

@app.get("/api/agent-catalog")
def get_agent_catalog():
    """角色目录（已迁移到新引擎，此端点保留兼容，返回空列表）。"""
    return {"agents": []}

# ============================================
# API — Optimize Prompt
# ============================================

class OptimizePromptRequest(BaseModel):
    task: str
    preset: dict

OPTIMIZE_SYSTEM_PROMPT = "You are a task optimizer. Rewrite user input into a clear, structured, executable task description. Preserve all key requirements. Output only the optimized task."

@app.post("/api/optimize-prompt")
async def optimize_prompt(req: OptimizePromptRequest):
    preset = req.preset
    config = AgentConfig(
        api_key=preset.get("api_key", ""),
        base_url=preset.get("base_url", ""),
        model=preset.get("model", ""),
        api_format=preset.get("api_format", "openai"),
        chat_template_kwargs=preset.get("chat_template_kwargs"),
    )
    user_prompt = f"Original task:\n{req.task}\n\nOutput the optimized task:"
    try:
        result = await call_llm(config, OPTIMIZE_SYSTEM_PROMPT, user_prompt, max_tokens=4000, request_timeout_seconds=60)
        if is_llm_error(result):
            raise HTTPException(status_code=500, detail=result)
        return {"optimized": result.strip(), "status": "success"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ============================================
# API — Skills
# ============================================

class SkillCreateRequest(BaseModel):
    name: str
    description: str = ""
    category: str = "custom"
    user_prompt: str = ""
    preset: dict = None

class SkillUpdateRequest(BaseModel):
    content: str
    description: str = ""
    category: str = "custom"
    tags: List[str] = []

class SkillFindRequest(BaseModel):
    query: str

@app.get("/api/skills")
def api_list_skills():
    try:
        skills = load_all_skills()
        return {"skills": skills, "status": "success"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/skills/{name}")
def api_get_skill(name: str):
    skill = load_skill_content(name)
    if not skill:
        raise HTTPException(status_code=404, detail=f"Skill not found: {name}")
    return {"skill": skill, "status": "success"}

@app.post("/api/skills/create")
async def api_create_skill(req: SkillCreateRequest):
    content = req.user_prompt.strip()
    if req.preset and req.preset.get("api_key"):
        config = AgentConfig(
            api_key=req.preset.get("api_key", ""),
            base_url=req.preset.get("base_url", ""),
            model=req.preset.get("model", ""),
            api_format=req.preset.get("api_format", "openai"),
        )
        try:
            result = await call_llm(config,
                "You are a skill creator. Generate a concise skill description in Markdown.",
                f"Skill name: {req.name}\nDescription: {req.description}\nUser prompt: {req.user_prompt}",
                max_tokens=2000, request_timeout_seconds=120)
            if not is_llm_error(result):
                content = result.strip()
        except Exception:
            pass
    save_skill(req.name, content, req.description, req.category)
    return {"status": "success", "name": req.name}

@app.put("/api/skills/{name}")
def api_update_skill(name: str, req: SkillUpdateRequest):
    save_skill(name, req.content, req.description, req.category, req.tags)
    return {"status": "success", "name": name}

@app.delete("/api/skills/{name}")
def api_delete_skill(name: str):
    delete_skill(name)
    return {"status": "success"}

@app.post("/api/skills/find")
def api_find_skill(req: SkillFindRequest):
    results = search_skills(req.query)
    return {"results": results, "status": "success"}

# ============================================
# API — Test Connection
# ============================================

@app.post("/api/test-connection")
async def test_connection(config: AgentConfig):
    start_time = time.time()
    api_key = config.api_key.strip()
    base_url = config.base_url.strip().strip("`").strip()
    model = config.model.strip()
    api_format = getattr(config, "api_format", "openai")

    if not api_key:
        return {"success": False, "message": "API Key not configured", "hint": "no_api_key"}
    if not base_url:
        return {"success": False, "message": "Base URL is empty", "hint": "no_base_url"}
    if not model:
        return {"success": False, "message": "Model name is empty", "hint": "no_model"}

    try:
        test_timeout = 45.0
        if api_format == "claude":
            import httpx
            headers = {"x-api-key": api_key, "anthropic-version": "2023-06-01", "content-type": "application/json"}
            payload = {"model": model, "max_tokens": 20, "messages": [{"role": "user", "content": "Say: OK"}], "temperature": 0.7}
            async with httpx.AsyncClient(timeout=test_timeout) as http_client:
                response = await http_client.post(base_url, json=payload, headers=headers)
            if response.status_code != 200:
                raise Exception(f"HTTP {response.status_code}")
            result = response.json()
            full_content = result.get("content", [{}])[0].get("text", "")
        else:
            client = __import__("openai").AsyncOpenAI(api_key=api_key, base_url=base_url, timeout=test_timeout, max_retries=0)
            kwargs = {"model": model, "messages": [{"role": "user", "content": "Say: OK"}], "max_tokens": 20, "stream": False}
            resp = await client.chat.completions.create(**kwargs)
            full_content = resp.choices[0].message.content or ""

        elapsed_ms = int((time.time() - start_time) * 1000)
        if full_content.strip():
            return {"success": True, "message": f"Connected ({elapsed_ms}ms)", "response": full_content.strip(), "model": model, "elapsed_ms": elapsed_ms}
        return {"success": False, "message": "Empty response", "elapsed_ms": elapsed_ms}
    except Exception as e:
        return {"success": False, "message": str(e)[:300], "elapsed_ms": int((time.time() - start_time) * 1000)}

# ============================================
# API — Test Execution
# ============================================

class TestExecRequest(BaseModel):
    instruction: str
    workspace_dir: str = ""

@app.post("/api/test/exec")
async def api_test_exec(req: TestExecRequest):
    ws_dir = req.workspace_dir or WORKSPACE_DIR
    result = await execute_test(req.instruction, ws_dir)
    return result.to_dict()

@app.get("/api/test/capabilities")
def api_test_capabilities():
    caps = {"terminal": True, "code_python": True, "code_node": True, "api_test": True, "playwright": False}
    try:
        __import__("playwright")
        caps["playwright"] = True
    except ImportError:
        pass
    return {"capabilities": caps}

class TestConfirmRequest(BaseModel):
    instruction: str
    workspace_dir: str = ""

@app.post("/api/test/confirm")
async def api_test_confirm(req: TestConfirmRequest):
    import re as _re
    cmd_match = _re.match(r"\[TEST:CMD:\s*(.+)\]$", req.instruction, re.IGNORECASE)
    if not cmd_match:
        return {"success": False, "error": "Only CMD tests support force execution"}
    result = await execute_terminal_force(cmd_match.group(1).strip(), req.workspace_dir or WORKSPACE_DIR)
    return result.to_dict()

class DepInstallRequest(BaseModel):
    module: str
    suggestion: str = ""

@app.post("/api/test/dep-install")
async def api_dep_install(req: DepInstallRequest):
    cmd = req.suggestion or f"pip install {req.module}"
    result_parts = []
    exit_code = -1
    async for chunk in terminal_executor_stream(cmd, WORKSPACE_DIR):
        await TerminalManager.broadcast(chunk)
        if chunk["type"] in ("stdout", "error"):
            result_parts.append(chunk.get("data", ""))
        if chunk["type"] == "done":
            exit_code = chunk.get("exit_code", -1)
    return {"success": exit_code == 0, "module": req.module, "command": cmd, "output": "\n".join(result_parts)[:2000], "exit_code": exit_code}

@app.websocket("/api/test/terminal/ws")
async def terminal_websocket(websocket: WebSocket):
    await websocket.accept()
    TerminalManager.connect(websocket)
    try:
        await websocket.send_json({"type": "connected", "data": f"Connected (cwd: {WORKSPACE_DIR})", "cwd": WORKSPACE_DIR, "elapsed": 0})
        while True:
            data = await websocket.receive_json()
            command = data.get("command", "")
            workspace_dir = data.get("workspace_dir", "")
            cwd = workspace_dir or WORKSPACE_DIR
            if is_dangerous(command):
                await websocket.send_json({"type": "dangerous", "command": command})
                continue
            async for chunk in terminal_executor_stream(command, cwd):
                await websocket.send_json(chunk)
                await TerminalManager.broadcast({**chunk, "source": "manual", "command": command})
    except Exception as e:
        try:
            await websocket.send_json({"type": "error", "data": f"Disconnected: {str(e)}", "elapsed": 0})
        except Exception:
            pass
    finally:
        TerminalManager.disconnect(websocket)

# ============================================
# API — Projects (v2, with SQLite project engine)
# ============================================
# 新版项目系统：一个项目文件夹 = 一个独立 SQLite 数据库 + 文件目录
# 支持：大纲/写作/审校 三阶段灵活切换，AI 助理，暂停恢复，侧边栏实时刷新
# ============================================

from project_db import (
    ProjectDB, list_all_projects, create_project, delete_project,
    get_project_file, get_project_dir, read_file_safe, write_file_safe,
    WORKSPACE_DIR as PDB_WS, PROJECTS_DIR as PDB_PJ,
)
from assistant import ProjectAssistant


class _ProjectCreate(BaseModel):
    name: str = ""
    title: str = ""
    genre: str = ""
    total_chapters: int = 0
    outline_review_mode: str = "manual"
    outline_layers: Optional[dict] = None
    extra_requirements: str = ""
    role_presets: Optional[dict] = None


class _ProjectPresets(BaseModel):
    manager: Optional[dict] = None
    worker: Optional[dict] = None
    reviewer: Optional[dict] = None
    chat: Optional[dict] = None


class _AssistantChat(BaseModel):
    message: str = ""
    presets: List[dict] = []


@app.get("/api/v2/projects")
def v2_list_projects():
    """新版项目列表（从 SQLite 读）。"""
    try:
        data = list_all_projects()
        return {"projects": data}
    except Exception as e:
        return {"projects": [], "error": str(e)}


@app.post("/api/v2/projects")
def v2_create_project(p: _ProjectCreate):
    """创建新项目。"""
    try:
        result = create_project(
            name=p.name or f"project_{int(time.time())}",
            title=p.title,
            genre=p.genre,
            total_chapters=p.total_chapters,
            outline_review_mode=p.outline_review_mode,
        )
        # 保存额外需求和角色预设到项目文件
        safe_name = result.get("name", p.name)
        if p.extra_requirements:
            write_file_safe(safe_name, "extra_requirements.txt", p.extra_requirements)
        if p.role_presets and isinstance(p.role_presets, dict):
            db = ProjectDB(safe_name)
            db.set_presets(
                manager=p.role_presets.get("manager"),
                worker=p.role_presets.get("worker"),
                reviewer=p.role_presets.get("reviewer"),
                chat=p.role_presets.get("chat"),
            )
            db.close()
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/api/v2/projects/{project_name}")
def v2_delete_project(project_name: str):
    """删除项目。"""
    try:
        ok = delete_project(project_name)
        return {"success": ok, "name": project_name}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


class _ProjectPatch(BaseModel):
    title: Optional[str] = None
    genre: Optional[str] = None
    total_chapters: Optional[int] = None
    outline_review_mode: Optional[str] = None
    word_count_min: Optional[int] = None
    word_count_max: Optional[int] = None
    max_rounds_writing: Optional[int] = None
    max_rounds_outline: Optional[int] = None


@app.patch("/api/v2/projects/{project_name}")
def v2_patch_project(project_name: str, body: _ProjectPatch):
    """部分更新项目信息（标题、题材等）。"""
    try:
        db = ProjectDB(project_name)
        kwargs = {}
        if body.title is not None:
            kwargs["title"] = body.title
        if body.genre is not None:
            kwargs["genre"] = body.genre
        if body.total_chapters is not None:
            kwargs["total_chapters"] = body.total_chapters
        if body.outline_review_mode is not None:
            kwargs["outline_review_mode"] = body.outline_review_mode
        if body.word_count_min is not None:
            kwargs["word_count_min"] = body.word_count_min
        if body.word_count_max is not None:
            kwargs["word_count_max"] = body.word_count_max
        if body.max_rounds_writing is not None:
            kwargs["max_rounds_writing"] = body.max_rounds_writing
        if body.max_rounds_outline is not None:
            kwargs["max_rounds_outline"] = body.max_rounds_outline
        if kwargs:
            db.update_project(**kwargs)
        data = db.to_dict()
        db.close()
        return {"success": True, "project": data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/v2/projects/{project_name}")
def v2_get_project(project_name: str):
    """读取单个项目的完整信息（给前端详情页用）。"""
    try:
        db = ProjectDB(project_name)
        data = db.to_dict()
        db.close()
        return data
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/v2/projects/{project_name}/presets")
def v2_get_project_presets(project_name: str):
    """读取项目的三角色模型预设。"""
    try:
        db = ProjectDB(project_name)
        presets = db.get_presets()
        db.close()
        return {"presets": presets}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.put("/api/v2/projects/{project_name}/presets")
def v2_update_project_presets(project_name: str, body: _ProjectPresets):
    """保存项目的角色模型预设（部分更新，只传要改的角色）。"""
    try:
        db = ProjectDB(project_name)
        ok = db.set_presets(
            manager=body.manager,
            worker=body.worker,
            reviewer=body.reviewer,
            chat=body.chat,
        )
        updated = db.get_presets()
        db.close()
        return {"success": ok, "presets": updated}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/v2/projects/{project_name}/chapters")
def v2_list_chapters(project_name: str):
    """章节列表（侧边栏用）。"""
    try:
        db = ProjectDB(project_name)
        chapters = db.list_chapters()
        db.close()
        return {"chapters": chapters}
    except Exception as e:
        return {"chapters": [], "error": str(e)}


@app.get("/api/v2/projects/{project_name}/chapters/{chapter_index}")
def v2_get_chapter(project_name: str, chapter_index: int):
    """读取单章正文。前端展示时清洗元数据标记，源文件保留。"""
    try:
        db = ProjectDB(project_name)
        chapter = db.get_chapter(chapter_index)
        db.close()
        if chapter is None:
            raise HTTPException(status_code=404, detail="Chapter not found")
        # 清洗元数据标记（---PREV/CAST/THREAD/STRAND---），源文件保留供写作引擎使用
        if chapter.get("content"):
            import re as _re
            chapter["content"] = _re.sub(r"^---(?:PREV|CAST|THREAD|STRAND)---\n?", "", chapter["content"], flags=_re.MULTILINE)
            chapter["content"] = _re.sub(r"\n{3,}", "\n\n", chapter["content"])
        return chapter
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.patch("/api/v2/projects/{project_name}/chapters/{chapter_index}")
def v2_update_chapter(project_name: str, chapter_index: int, body: dict):
    """人工编辑章节（标题/摘要/正文）。"""
    try:
        db = ProjectDB(project_name)
        title = body.get("title", "")
        summary = body.get("summary", "")
        content = body.get("content", None)
        status = body.get("status", "drafted")
        db.upsert_chapter(
            chapter_index=chapter_index,
            title=title,
            summary=summary,
            status=status,
            content=content,
        )
        db.close()
        return {"success": True, "chapter_index": chapter_index}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/v2/projects/{project_name}/memory")
def v2_list_memory(project_name: str):
    """记忆条目列表。"""
    try:
        db = ProjectDB(project_name)
        items = db.list_memory()
        db.close()
        return {"memory": items}
    except Exception as e:
        return {"memory": [], "error": str(e)}


@app.post("/api/v2/projects/{project_name}/memory")
def v2_add_memory(project_name: str, body: dict):
    """添加一条记忆。"""
    try:
        db = ProjectDB(project_name)
        mem_type = body.get("type", "note")
        content = body.get("content", "")
        chapter_ref = int(body.get("chapter_ref", 0) or 0)
        db.add_memory(mem_type, content, chapter_ref)
        db.close()
        return {"success": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/v2/projects/{project_name}/confirm-outline")
def v2_confirm_outline(project_name: str):
    """人工审查大纲后，推进到写作阶段。"""
    try:
        db = ProjectDB(project_name)
        db.update_project(current_stage="writing")
        data = db.to_dict()
        db.close()
        return {"success": True, "stage": "writing", "project": data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/v2/projects/{project_name}/reject-outline")
def v2_reject_outline(project_name: str):
    """审查不通过，停留在 outline 状态。"""
    try:
        db = ProjectDB(project_name)
        db.update_project(current_stage="outline")
        data = db.to_dict()
        db.close()
        return {"success": True, "stage": "outline", "project": data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/v2/projects/{project_name}/confirm-writing")
def v2_confirm_writing(project_name: str):
    """写作完成后，推进到审校阶段。"""
    try:
        db = ProjectDB(project_name)
        db.update_project(current_stage="review")
        data = db.to_dict()
        db.close()
        return {"success": True, "stage": "review", "project": data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/v2/projects/{project_name}/confirm-review")
def v2_confirm_review(project_name: str):
    """审校完成，标记项目为已完成。"""
    try:
        db = ProjectDB(project_name)
        db.update_project(current_stage="done")
        data = db.to_dict()
        db.close()
        return {"success": True, "stage": "done", "project": data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/v2/projects/migrate-old")
def v2_migrate_old_projects(body: dict = {}):
    """迁移旧 run_* 目录到新项目系统。支持 dry-run。"""
    import subprocess
    dry = "1" if body.get("dry_run", False) else ""
    force = "1" if body.get("force", False) else ""
    cmd = ["python", os.path.join(os.path.dirname(os.path.abspath(__file__)), "migration.py")]
    if dry:
        cmd.append("--dry-run")
    if force:
        cmd.append("--force")
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120,
                                cwd=os.path.dirname(os.path.abspath(__file__)))
        return {
            "success": result.returncode == 0,
            "stdout": result.stdout,
            "stderr": result.stderr,
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


# ============================================
# API — Project Assistant (AI Chat)
# ============================================

@app.post("/api/v2/projects/{project_name}/assistant/chat")
def v2_assistant_chat(project_name: str, body: _AssistantChat):
    """项目 AI 助理：结合项目上下文，自然语言问答。"""
    try:
        pa = ProjectAssistant(project_name, body.presets or [])
        reply = pa.chat(body.message)
        return {"success": True, "reply": reply, "project_name": project_name}
    except Exception as e:
        return {"success": False, "reply": f"(助理出错：{e})", "error": str(e)}


class _AiAddCharacter(BaseModel):
    description: str
    presets: List[dict] = []
    preset_name: str = ""  # 指定使用哪个预设（AI 对话模型）


class _DeleteCharacter(BaseModel):
    name: str  # 要删除的角色名
    presets: List[dict] = []
    preset_name: str = ""


def _remove_character_from_md(md: str, name: str) -> Tuple[str, bool]:
    """
    从 characters.md 中删除名为 name 的角色块。
    块定义为：以 N. **name** 开头的行（后跟缩进属性），直到下一个 N. 块或 ## 标题前。
    返回 (new_md, found)。
    """
    lines = md.split("\n")
    out = []
    i = 0
    found = False
    name_pat = re.compile(r"^\s*\d+[\.、]\s*\**" + re.escape(name) + r"\**\s*[:：]?\s*$")
    while i < len(lines):
        line = lines[i]
        if not found and name_pat.match(line):
            # 找到目标，删除本行 + 后续缩进行
            found = True
            i += 1
            while i < len(lines):
                nxt = lines[i]
                # 下一段编号 或 下一个 ## 标题 → 停止删除
                if re.match(r"^\s*\d+[\.、]\s*\*", nxt) or nxt.lstrip().startswith("## "):
                    break
                # 顶级 # 标题也停止
                if nxt.lstrip().startswith("# ") and not nxt.lstrip().startswith("## "):
                    break
                i += 1
            # 删完后回退一步以便外层 while 能处理这个新行
            # 但其实我们已经把它从 out 跳过了，不需要回退
            continue
        out.append(line)
        i += 1
    return ("\n".join(out), found)


@app.post("/api/v2/projects/{project_name}/delete-character")
def v2_delete_character(project_name: str, body: _DeleteCharacter):
    """
    删除指定名称的角色。
    可选：先用 AI 校验要删除的 name 是否与文件中某个角色匹配（模糊匹配）。
    """
    try:
        if not body.name.strip():
            return {"success": False, "error": "角色名不能为空"}

        char_path = get_project_file(project_name, "characters.md")
        if not os.path.exists(char_path):
            return {"success": False, "error": "characters.md 不存在"}

        with open(char_path, "r", encoding="utf-8") as f:
            content = f.read()

        # 先按精确名字匹配，找不到则尝试去掉空格
        target = body.name.strip()
        new_content, found = _remove_character_from_md(content, target)
        if not found:
            # 尝试全角/半角规整
            for ch in [target.replace(" ", ""), target.replace("：", ":"), target.strip("**")]:
                new_content, found = _remove_character_from_md(content, ch)
                if found:
                    break

        if not found:
            return {"success": False, "error": f"未找到角色「{target}」"}

        # 清理：把因删除留下的连续空行合并
        new_content = re.sub(r"\n{3,}", "\n\n", new_content).rstrip() + "\n"

        with open(char_path, "w", encoding="utf-8") as f:
            f.write(new_content)

        # 更新 memory
        db = ProjectDB(project_name)
        db.add_memory("character", f"删除角色：{target}", 0)
        db.close()

        return {
            "success": True,
            "removed": target,
            "file_path": "characters.md",
            "size": len(new_content),
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.post("/api/v2/projects/{project_name}/ai-add-character")
def v2_ai_add_character(project_name: str, body: _AiAddCharacter):
    """
    使用 AI 把作者的自然语言人物描述，转换为符合 characters.md 格式的 markdown
    并自动追加到文件中。
    """
    try:
        if not body.description.strip():
            return {"success": False, "error": "描述不能为空"}

        # 1. 读取现有 characters.md
        char_path = get_project_file(project_name, "characters.md")
        existing = ""
        if os.path.exists(char_path):
            with open(char_path, "r", encoding="utf-8") as f:
                existing = f.read()

        # 2. 调 LLM 生成格式化的人物条目
        pa = ProjectAssistant(project_name, body.presets or [], body.preset_name or "")
        new_block = pa.format_character(body.description, existing)

        if not new_block or new_block.startswith("<!--"):
            return {
                "success": False,
                "error": new_block or "AI 未能生成人物条目（请检查 AI 对话模型配置）",
            }

        # 3. 拼接到文件：如果文件为空就先建一个最小骨架，否则追加在末尾
        if not existing.strip():
            # 先取一下项目名/标题
            db = ProjectDB(project_name)
            info = db.get_project()
            db.close()
            proj_title = info.get("title") or project_name
            new_content = (
                f"# 《{proj_title}》主要人物设定\n\n"
                f"## 人物列表\n\n"
                f"{new_block}\n"
            )
        else:
            # 尝试在「## 人物列表」之后插入；否则直接追加到末尾
            marker = "## 人物列表"
            if marker in existing:
                # 在 人物列表 段尾插入：在该段后下一个 ## 标题之前
                # 简化策略：把 人物列表 这一段所有内容都取出，在它后面追加
                parts = existing.split(marker, 1)
                head = parts[0]  # 包含 # 标题 + 人物列表 标题
                rest = parts[1]  # 人物列表标题之后的内容
                # 找到 rest 中下一个 ## 标题位置
                m = re.search(r"^## ", rest, flags=re.MULTILINE)
                if m:
                    body_section = rest[:m.start()]
                    tail_section = rest[m.start():]
                    # body_section 末尾去多余空行
                    body_section = body_section.rstrip() + "\n\n" + new_block + "\n\n"
                    new_content = head + marker + body_section + tail_section
                else:
                    # 没有下一个标题，直接追加
                    new_content = existing.rstrip() + "\n\n" + new_block + "\n"
            else:
                new_content = existing.rstrip() + "\n\n" + new_block + "\n"

        # 4. 写回文件
        os.makedirs(os.path.dirname(char_path), exist_ok=True)
        with open(char_path, "w", encoding="utf-8") as f:
            f.write(new_content)

        # 5. 更新 memory
        db = ProjectDB(project_name)
        db.add_memory("character", f"AI 添加人物设定（{len(new_block)}字）", 0)
        db.close()

        return {
            "success": True,
            "new_block": new_block,
            "file_path": "characters.md",
            "size": len(new_content),
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.post("/api/v2/projects/{project_name}/assistant/suggest-next")
def v2_assistant_suggest_next(project_name: str, body: dict = {}):
    """建议下一章节怎么写。"""
    try:
        presets = body.get("presets", []) if body else []
        pa = ProjectAssistant(project_name, presets)
        reply = pa.suggest_next_chapter()
        return {"success": True, "reply": reply}
    except Exception as e:
        return {"success": False, "reply": "", "error": str(e)}


@app.post("/api/v2/projects/{project_name}/assistant/analyze-consistency")
def v2_assistant_analyze(project_name: str, body: dict = {}):
    """检查全文一致性问题。"""
    try:
        presets = body.get("presets", []) if body else []
        pa = ProjectAssistant(project_name, presets)
        reply = pa.analyze_consistency()
        return {"success": True, "reply": reply}
    except Exception as e:
        return {"success": False, "reply": "", "error": str(e)}


@app.get("/api/v2/projects/{project_name}/chat")
def v2_list_chat_history(project_name: str):
    """对话历史记录。"""
    try:
        db = ProjectDB(project_name)
        chat = db.list_chat()
        db.close()
        return {"chat": chat}
    except Exception as e:
        return {"chat": [], "error": str(e)}


# ============================================
# API — Raw file access (项目文件直接读写)
# ============================================

@app.get("/api/v2/projects/{project_name}/file/{file_path:path}")
def v2_get_project_file(project_name: str, file_path: str):
    """读取项目内任意文件（outline.md, characters.md 等）。
    章节文件（chapters/*.txt）返回时清洗元数据标记，源文件保留。
    """
    try:
        project_dir = get_project_dir(project_name)
        full_path = safe_join(project_dir, file_path)
        if not os.path.exists(full_path):
            raise HTTPException(status_code=404, detail="File not found")
        with open(full_path, "r", encoding="utf-8") as f:
            content = f.read()
        # 章节文件：清洗元数据标记（---PREV/CAST/THREAD/STRAND---），
        # 源文件保留这些标记供写作引擎使用，前端展示时隐藏
        if file_path.startswith("chapters/") and file_path.endswith(".txt"):
            import re as _re
            content = _re.sub(r"^---(?:PREV|CAST|THREAD|STRAND)---\n?", "", content, flags=_re.MULTILINE)
            content = _re.sub(r"\n{3,}", "\n\n", content)
        return {"path": file_path, "content": content}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.put("/api/v2/projects/{project_name}/file/{file_path:path}")
def v2_put_project_file(project_name: str, file_path: str, body: dict):
    """写入项目内任意文件。"""
    try:
        project_dir = get_project_dir(project_name)
        content = body.get("content", "")
        full_path = safe_join(project_dir, file_path)
        os.makedirs(os.path.dirname(full_path), exist_ok=True)
        with open(full_path, "w", encoding="utf-8") as f:
            f.write(content)
        # 如果是大纲或人物设定，顺便更新 memory 条目
        db = ProjectDB(project_name)
        if file_path == "outline.md":
            db.add_memory("outline", f"outline.md 已手工更新（{len(content)}字）", 0)
        elif file_path == "characters.md":
            db.add_memory("character", f"characters.md 已手工更新（{len(content)}字）", 0)
        db.close()
        return {"success": True, "file": file_path, "size": len(content)}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============================================
# Startup
# ============================================

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
