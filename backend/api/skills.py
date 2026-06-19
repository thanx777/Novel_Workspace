"""
技能管理 — /api/skills
"""
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from .shared import limiter
from .skill_loader import load_all_skills, load_skill_content, save_skill, delete_skill, search_skills

router = APIRouter(prefix="/api", tags=["skills"])


# ── Request models ───────────────────────────────────────────────────

class SkillCreateRequest(BaseModel):
    name: str
    description: str = ""
    category: str = "custom"
    user_prompt: str = ""
    preset: Optional[dict] = None


class SkillUpdateRequest(BaseModel):
    content: str
    description: str = ""
    category: str = "custom"
    tags: List[str] = []


class SkillFindRequest(BaseModel):
    query: str


# ── Endpoints ────────────────────────────────────────────────────────

@router.get("/skills")
@limiter.limit("60/minute")
def api_list_skills(request: Request):
    try:
        skills = load_all_skills()
        return {"skills": skills, "status": "success"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/skills/{name}")
@limiter.limit("60/minute")
def api_get_skill(request: Request, name: str):
    skill = load_skill_content(name)
    if not skill:
        raise HTTPException(status_code=404, detail=f"Skill not found: {name}")
    return {"skill": skill, "status": "success"}


@router.post("/skills/create")
@limiter.limit("10/minute")
async def api_create_skill(request: Request, req: SkillCreateRequest):
    content = req.user_prompt.strip()
    if req.preset and req.preset.get("api_key"):
        from engines.common.llm_client import AgentConfig, call_llm, LLMError
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
            content = result.strip()
        except LLMError:
            pass
        except Exception:
            pass
    save_skill(req.name, content, req.description, req.category)
    return {"status": "success", "name": req.name}


@router.put("/skills/{name}")
@limiter.limit("60/minute")
def api_update_skill(request: Request, name: str, req: SkillUpdateRequest):
    save_skill(name, req.content, req.description, req.category, req.tags)
    return {"status": "success", "name": name}


@router.delete("/skills/{name}")
@limiter.limit("60/minute")
def api_delete_skill(request: Request, name: str):
    delete_skill(name)
    return {"status": "success"}


@router.post("/skills/find")
@limiter.limit("60/minute")
def api_find_skill(request: Request, req: SkillFindRequest):
    results = search_skills(req.query)
    return {"results": results, "status": "success"}
