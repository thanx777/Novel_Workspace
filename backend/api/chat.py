from fastapi import APIRouter

from project_db import get_project_dir
from knowledge_graph import KnowledgeGraph
from engines.outline.engine import OutlineEngine
from engines.writing.engine import WritingEngine
from .schemas import EngineChatRequest
from .engine_registry import _get_project_presets, _get_project_genre, _get_global_presets

router = APIRouter()


@router.post("/projects/{name}/outline/chat")
async def outline_chat(name: str, req: EngineChatRequest):
    """大纲 AI 对话。"""
    project_dir = get_project_dir(name)
    project_presets = _get_project_presets(name)
    global_presets = _get_global_presets()
    kg = KnowledgeGraph(project_dir)
    kg.load()

    engine = OutlineEngine(
        project_dir, name,
        project_presets=project_presets,
        global_presets=global_presets,
        kg=kg,
        genre=_get_project_genre(name),
    )
    response = await engine.chat(req.message, layer=req.layer)
    return {"response": response}


@router.post("/projects/{name}/writing/chat")
async def writing_chat(name: str, req: EngineChatRequest):
    """写作 AI 对话。"""
    project_dir = get_project_dir(name)
    project_presets = _get_project_presets(name)
    global_presets = _get_global_presets()
    kg = KnowledgeGraph(project_dir)
    kg.load()

    engine = WritingEngine(
        project_dir, name,
        project_presets=project_presets,
        global_presets=global_presets,
        kg=kg,
        genre=_get_project_genre(name),
    )
    response = await engine.chat(req.message, chapter_num=req.chapter)
    return {"response": response}
