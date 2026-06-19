"""
测试执行 & 连接测试 & 终端 WebSocket — /api/test-connection, /api/test/...
"""
import time

from fastapi import APIRouter, HTTPException, Request, WebSocket, Depends
from pydantic import BaseModel

from .shared import limiter, WORKSPACE_DIR
from .auth import require_admin, is_auth_disabled

from test_runner import (
    execute_test, terminal_executor_stream, is_dangerous, execute_terminal_force,
)

router = APIRouter(prefix="/api", tags=["test-exec"])


# ── WebSocket Terminal Manager ───────────────────────────────────────

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


# ── Request models ───────────────────────────────────────────────────

class TestExecRequest(BaseModel):
    instruction: str
    workspace_dir: str = ""


class TestConfirmRequest(BaseModel):
    instruction: str
    workspace_dir: str = ""


class DepInstallRequest(BaseModel):
    module: str
    suggestion: str = ""


# ── Endpoints ────────────────────────────────────────────────────────

@router.post("/test-connection")
@limiter.limit("10/minute")
async def test_connection(request: Request, config: dict):
    """测试 LLM API 连接。config 应包含 api_key, base_url, model, api_format。"""
    from engines.common.llm_client import AgentConfig
    start_time = time.time()
    api_key = config.get("api_key", "").strip()
    base_url = config.get("base_url", "").strip().strip("`").strip()
    model = config.get("model", "").strip()
    api_format = config.get("api_format", "openai")

    if not api_key:
        raise HTTPException(status_code=400, detail="API Key not configured")
    if not base_url:
        raise HTTPException(status_code=400, detail="Base URL is empty")
    if not model:
        raise HTTPException(status_code=400, detail="Model name is empty")

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
        raise HTTPException(status_code=502, detail="Empty response")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)[:300])


@router.post("/test/exec")
@limiter.limit("60/minute")
async def api_test_exec(request: Request, req: TestExecRequest):
    ws_dir = req.workspace_dir or WORKSPACE_DIR
    result = await execute_test(req.instruction, ws_dir)
    return result.to_dict()


@router.get("/test/capabilities")
@limiter.limit("60/minute")
def api_test_capabilities(request: Request):
    caps = {"terminal": True, "code_python": True, "code_node": True, "api_test": True, "playwright": False}
    try:
        __import__("playwright")
        caps["playwright"] = True
    except ImportError:
        pass
    return {"capabilities": caps}


@router.post("/test/confirm")
@limiter.limit("60/minute")
async def api_test_confirm(request: Request, req: TestConfirmRequest):
    import re as _re
    cmd_match = _re.match(r"\[TEST:CMD:\s*(.+)\]$", req.instruction, re.IGNORECASE)
    if not cmd_match:
        raise HTTPException(status_code=400, detail="Only CMD tests support force execution")
    result = await execute_terminal_force(cmd_match.group(1).strip(), req.workspace_dir or WORKSPACE_DIR)
    return result.to_dict()


@router.post("/test/dep-install")
@limiter.limit("60/minute")
async def api_dep_install(request: Request, req: DepInstallRequest, user=Depends(require_admin)):
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


@router.websocket("/test/terminal/ws")
async def terminal_websocket(websocket: WebSocket):
    # WebSocket 认证：从 query 参数读取 token
    if not is_auth_disabled():
        token = websocket.query_params.get("token", "")
        if not token:
            await websocket.close(code=4001, reason="Not authenticated")
            return
        try:
            from jose import jwt as _jwt
            from .auth import get_auth_secret, ALGORITHM
            payload = _jwt.decode(token, get_auth_secret(), algorithms=[ALGORITHM])
            role = payload.get("role", "user")
            if role != "admin":
                await websocket.close(code=4003, reason="Admin access required")
                return
        except Exception:
            await websocket.close(code=4001, reason="Invalid token")
            return
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
