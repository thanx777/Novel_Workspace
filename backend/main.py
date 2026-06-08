"""
Novel Forge — FastAPI application entry point.
Imports the execution engine from executor.py and exposes API routes.
"""
import asyncio
import json
import os
import re
import shutil
import time
from fastapi import FastAPI, HTTPException, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from sse_starlette.sse import EventSourceResponse
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
from collections import defaultdict

# Import engine core from executor.py
from executor import (
    WORKSPACE_DIR, PROJECTS_DIR,
    AgentConfig, NodeInfo, ConnectionInfo,
    GraphTaskRequest, OptimizePromptRequest,
    FileContent, WorkspaceConfig,
    GraphExecutor,
    call_llm, is_llm_error, resolve_system_prompt,
    extract_and_save_files, get_safe_path, get_full_path,
    _count_chapters, _resolve_workspace_dir,
    FRAMEWORK_PROMPTS, FRAMEWORK_PROMPTS_STANDARD, FRAMEWORK_PROMPTS_COMPATIBLE,
    MODE_CONFIG, MAX_TOKENS_BY_TYPE, DEFAULT_MAX_TOKENS, DEFAULT_STAGE_TIMEOUT_SECONDS,
    REQUEST_TIMEOUT,
    ALL_AGENTS, ALL_SKILLS,
    load_all_agents, build_role_catalog, get_agent_by_name,
    load_all_skills, load_skill_content, save_skill, delete_skill, search_skills,
)
from agent_loader import load_all_agents as _load_agents, build_role_catalog as _build_catalog, get_agent_by_name as _get_agent
from skill_loader import load_all_skills as _load_skills, load_skill_content as _load_skill, save_skill as _save_skill, delete_skill as _del_skill, search_skills as _search_skills
from test_runner import parse_test_instructions, execute_test, terminal_executor_stream, is_dangerous, execute_terminal_force

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

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

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
    target_dir = os.path.join(WORKSPACE_DIR, folder) if folder else WORKSPACE_DIR
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
        os.makedirs(os.path.join(WORKSPACE_DIR, folder), exist_ok=True)
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
# API — Tasks
# ============================================

@app.get("/api/tasks")
def list_tasks():
    tasks = []
    if not os.path.isdir(WORKSPACE_DIR):
        return {"tasks": tasks}
    for entry in sorted(os.listdir(WORKSPACE_DIR), reverse=True):
        folder = os.path.join(WORKSPACE_DIR, entry)
        if not os.path.isdir(folder) or not entry.startswith("run_"):
            continue
        state_path = os.path.join(folder, "state.json")
        if not os.path.exists(state_path):
            continue
        try:
            with open(state_path, "r", encoding="utf-8") as f:
                state = json.load(f)
        except Exception:
            continue
        chapters_done = len(_count_chapters(state.get("saved_files", [])))
        task_text = state.get("task", "")
        ch_match = re.search(r"(\d+)\s*[章章]|(\d+)\s*chapters?", task_text)
        total_ch = int(ch_match.group(1)) if ch_match else 0
        if chapters_done >= total_ch > 0:
            status = "completed"
        elif state.get("round_idx", 0) > 0:
            status = "in_progress"
        else:
            status = "unknown"
        tasks.append({
            "folder": entry,
            "task": task_text[:80],
            "novel_stage": state.get("novel_stage", ""),
            "execution_mode": state.get("execution_mode", "standard"),
            "chapters_done": chapters_done,
            "total_chapters": total_ch,
            "round_idx": state.get("round_idx", 0),
            "updated": state.get("updated", ""),
            "status": status,
        })
    return {"tasks": tasks}

@app.get("/api/tasks/{folder}")
def get_task_state(folder: str):
    if ".." in folder or "/" in folder or "\\" in folder:
        raise HTTPException(status_code=400, detail="Invalid folder")
    state = GraphExecutor.load_checkpoint(folder)
    if not state:
        raise HTTPException(status_code=404, detail="Checkpoint not found")
    ch_nums = _count_chapters(state.get("saved_files", []))
    return {
        "folder": folder,
        "task": state.get("task", ""),
        "nodes": state.get("nodes", []),
        "connections": state.get("connections", []),
        "presets": state.get("presets", {}),
        "execution_mode": state.get("execution_mode", "standard"),
        "novel_stage": state.get("novel_stage", ""),
        "chapters_done": len(ch_nums),
        "updated": state.get("updated", ""),
        "conversation_history": state.get("conversation_history", []),
    }

@app.post("/api/tasks/{folder}/resume")
async def resume_task(folder: str):
    if ".." in folder or "/" in folder or "\\" in folder:
        raise HTTPException(status_code=400, detail="Invalid folder")
    state = GraphExecutor.load_checkpoint(folder)
    if not state:
        raise HTTPException(status_code=404, detail="Checkpoint not found")

    nodes = [NodeInfo(id=n["id"], type=n["type"], config=n.get("config", {})) for n in state.get("nodes", [])]
    connections = [ConnectionInfo(
        id=c["id"], from_node=c.get("from", c.get("from_node", "")),
        from_port=c.get("fromPort", c.get("from_port", "")),
        to_node=c.get("to", c.get("to_node", "")),
        to_port=c.get("toPort", c.get("to_port", "")),
        annotation=c.get("annotation", ""),
    ) for c in state.get("connections", [])]
    presets_list = [v for v in state.get("presets", {}).values()] if isinstance(state.get("presets"), dict) else state.get("presets", [])

    executor = GraphExecutor(
        nodes=nodes, connections=connections,
        task=state.get("task", ""),
        presets=presets_list,
        skills=state.get("skills", []),
        conversation_history=state.get("conversation_history", []),
        execution_mode=state.get("execution_mode", "standard"),
        run_subfolder=state.get("run_subfolder", folder),
        outline_review_mode=state.get("outline_review_mode", "auto"),
    )
    executor.outputs = state.get("outputs", {})
    executor.saved_files = state.get("saved_files", [])
    executor.active_skills = state.get("active_skills", [])
    executor._novel_stage = state.get("novel_stage", "")
    executor.node_icons = state.get("node_icons", {})
    executor.node_roles = state.get("node_roles", {})
    executor._guard_override = state.get("guard_override", "")
    executor._consecutive_approvals = state.get("consecutive_approvals", 0)
    executor._novel_summary = state.get("novel_summary", "")
    executor._novel_memory = state.get("novel_memory", "")
    executor._completed_stages = state.get("completed_stages", [])
    executor._load_memory_from_disk()

    async def event_generator():
        q = asyncio.Queue()
        def q_yield(msg):
            q.put_nowait(msg)
        # 使用 execute() 而非 _execute_phase_graph()，以正确恢复流水线
        exec_task = asyncio.create_task(executor.execute(q_yield))
        while True:
            try:
                msg = await asyncio.wait_for(q.get(), timeout=0.5)
                yield {"data": json.dumps(msg, ensure_ascii=False)}
            except asyncio.TimeoutError:
                if exec_task.done():
                    if exec_task.exception():
                        yield {"data": json.dumps({"status": "error", "message": str(exec_task.exception())}, ensure_ascii=False)}
                    break
    return EventSourceResponse(event_generator())

@app.delete("/api/tasks/{folder}")
def delete_task(folder: str):
    if ".." in folder or "/" in folder or "\\" in folder:
        raise HTTPException(status_code=400, detail="Invalid folder")
    path = os.path.join(WORKSPACE_DIR, folder)
    if os.path.isdir(path):
        shutil.rmtree(path)
        return {"status": "success"}
    if os.path.exists(path):
        os.remove(path)
        return {"status": "success"}
    raise HTTPException(status_code=404, detail="Task not found")


@app.patch("/api/tasks/{folder}")
def update_task(folder: str, body: dict):
    if ".." in folder or "/" in folder or "\\" in folder:
        raise HTTPException(status_code=400, detail="Invalid folder")
    state_path = os.path.join(WORKSPACE_DIR, folder, "state.json")
    if not os.path.exists(state_path):
        raise HTTPException(status_code=404, detail="Task not found")
    try:
        with open(state_path, "r", encoding="utf-8") as f:
            state = json.load(f)
    except Exception:
        raise HTTPException(status_code=500, detail="Failed to read state")
    # Update allowed fields
    if "task" in body:
        state["task"] = body["task"]
    if "execution_mode" in body:
        state["execution_mode"] = body["execution_mode"]
    if "nodes" in body:
        state["nodes"] = body["nodes"]
    if "presets" in body:
        state["presets"] = body["presets"]
    tmp_path = state_path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
    os.replace(tmp_path, state_path)
    return {"status": "success"}

# ============================================
# API — Prompt Templates & Agent Catalog
# ============================================

@app.get("/api/prompt-templates")
def get_prompt_templates():
    frameworks = {}
    for key, prompt in FRAMEWORK_PROMPTS.items():
        frameworks[key] = {
            "name": {"manager": "Manager", "worker": "Worker", "reviewer": "Reviewer"}.get(key, key),
            "icon": {"manager": "🎯", "worker": "⚡", "reviewer": "🔍"}.get(key, "🤖"),
            "desc": prompt[:80].replace("\n", " "),
            "role": key,
        }
    return {"frameworks": frameworks}

@app.get("/api/agent-catalog")
def get_agent_catalog():
    agents = []
    for a in ALL_AGENTS:
        agents.append({
            "name": a["name"],
            "description": a["description"],
            "emoji": a["emoji"],
            "department": a["department"],
        })
    return {"agents": agents}

# ============================================
# API — Optimize Prompt
# ============================================

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
        skills = _load_skills()
        return {"skills": skills, "status": "success"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/skills/{name}")
def api_get_skill(name: str):
    skill = _load_skill(name)
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
    _save_skill(req.name, content, req.description, req.category)
    return {"status": "success", "name": req.name}

@app.put("/api/skills/{name}")
def api_update_skill(name: str, req: SkillUpdateRequest):
    _save_skill(name, req.content, req.description, req.category, req.tags)
    return {"status": "success", "name": name}

@app.delete("/api/skills/{name}")
def api_delete_skill(name: str):
    _del_skill(name)
    return {"status": "success"}

@app.post("/api/skills/find")
def api_find_skill(req: SkillFindRequest):
    results = _search_skills(req.query)
    return {"results": results, "status": "success"}

# ============================================
# API — Run Task & Feedback
# ============================================

@app.post("/api/run-task/feedback")
async def send_feedback(feedback: dict):
    executor = GraphExecutor._current_executor
    if executor and not executor.cancelled:
        await executor.feedback_queue.put(feedback.get("message", ""))
        return {"status": "accepted"}
    return {"status": "no_active_executor"}

@app.post("/api/stop-task")
def stop_task():
    stopped = 0
    if GraphExecutor._current_executor:
        GraphExecutor._current_executor.cancelled = True
        stopped += 1
    for ex in list(GraphExecutor._active_executors):
        ex.cancelled = True
        stopped += 1
    GraphExecutor._active_executors.clear()
    return {"status": "stopped", "count": stopped}

@app.post("/api/run-task")
async def run_task(req: GraphTaskRequest):
    return EventSourceResponse(_run_graph_task(req))

async def _run_graph_task(req: GraphTaskRequest):
    executor = GraphExecutor(
        nodes=req.nodes,
        connections=req.connections,
        task=req.task,
        presets=req.presets,
        skills=req.skills,
        conversation_history=req.conversation_history,
        execution_mode=req.execution_mode,
        outline_review_mode=getattr(req, 'outline_review_mode', 'auto'),
    )
    q = asyncio.Queue()
    def q_yield(msg):
        q.put_nowait(msg)
    exec_task = asyncio.create_task(executor.execute(q_yield))
    while True:
        try:
            msg = await asyncio.wait_for(q.get(), timeout=0.5)
            yield {"data": json.dumps(msg, ensure_ascii=False)}
        except asyncio.TimeoutError:
            if exec_task.done():
                while not q.empty():
                    try:
                        msg = q.get_nowait()
                        yield {"data": json.dumps(msg, ensure_ascii=False)}
                    except asyncio.QueueEmpty:
                        break
                break
    await exec_task

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
# Startup
# ============================================

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
