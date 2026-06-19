"""
角色目录 & 提示词优化 — /api/prompt-templates, /api/agent-catalog, /api/optimize-prompt
"""
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from .shared import limiter

router = APIRouter(prefix="/api", tags=["agent-catalog"])


# ── Request models ───────────────────────────────────────────────────

class OptimizePromptRequest(BaseModel):
    task: str
    preset: dict


OPTIMIZE_SYSTEM_PROMPT = "You are a task optimizer. Rewrite user input into a clear, structured, executable task description. Preserve all key requirements. Output only the optimized task."


# ── Endpoints ────────────────────────────────────────────────────────

@router.get("/prompt-templates")
@limiter.limit("60/minute")
def get_prompt_templates(request: Request):
    """提示词模板列表（已迁移到新引擎，此端点保留兼容）。"""
    return {"frameworks": {}}


@router.get("/agent-catalog")
@limiter.limit("60/minute")
def get_agent_catalog(request: Request):
    """角色目录（已迁移到新引擎，此端点保留兼容，返回空列表）。"""
    return {"agents": []}


@router.post("/optimize-prompt")
@limiter.limit("10/minute")
async def optimize_prompt(request: Request, req: OptimizePromptRequest):
    from engines.common.llm_client import AgentConfig, call_llm, LLMError
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
        return {"optimized": result.strip(), "status": "success"}
    except LLMError as e:
        raise HTTPException(status_code=500, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
