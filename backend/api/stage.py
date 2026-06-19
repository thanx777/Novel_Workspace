from fastapi import APIRouter, Depends

from project_db import ProjectDB, get_project_dir
from knowledge_graph import KnowledgeGraph
from engines.outline.engine import OutlineEngine
from engines.writing.engine import WritingEngine
from engines.review.engine import ReviewEngine
from .schemas import OutlineGenerateRequest, WritingStartRequest
from .engine_registry import _get_project_presets, _get_project_genre, _get_global_presets
from .auth import require_auth

router = APIRouter()


# ---- 大纲引擎 ----

@router.post("/projects/{name}/outline/generate")
async def outline_generate(name: str, req: OutlineGenerateRequest, user=Depends(require_auth)):
    """触发大纲 MWR 循环生成。"""
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

    if req.layer:
        return await engine.generate_layer(req.layer, requirements=req.requirements)
    else:
        return await engine.generate_all(requirements=req.requirements)


@router.get("/projects/{name}/outline/state")
def outline_state(name: str):
    """获取大纲引擎状态。"""
    project_dir = get_project_dir(name)
    project_presets = _get_project_presets(name)
    global_presets = _get_global_presets()
    engine = OutlineEngine(project_dir, name, project_presets=project_presets, global_presets=global_presets,
                           genre=_get_project_genre(name))
    return engine.get_status()


# ---- 写作引擎 ----

@router.post("/projects/{name}/writing/start")
async def writing_start(name: str, req: WritingStartRequest, user=Depends(require_auth)):
    """启动写作引擎。"""
    project_dir = get_project_dir(name)
    db = ProjectDB(name)
    project_presets = db.get_presets()
    global_presets = _get_global_presets()
    kg = KnowledgeGraph(project_dir)
    kg.load()

    total = req.total_chapters or db.get_project().get("total_chapters", 0)

    engine = WritingEngine(
        project_dir, name,
        project_presets=project_presets,
        global_presets=global_presets,
        kg=kg,
        total_chapters=total,
        genre=_get_project_genre(name),
    )

    if req.start_chapter > 1:
        return await engine.write_chapter(req.start_chapter)
    else:
        return await engine.write_all(start_chapter=req.start_chapter)


@router.get("/projects/{name}/writing/state")
def writing_state(name: str):
    """获取写作引擎状态。"""
    project_dir = get_project_dir(name)
    db = ProjectDB(name)
    project_presets = db.get_presets()
    global_presets = _get_global_presets()

    total = db.get_project().get("total_chapters", 0)
    engine = WritingEngine(project_dir, name, project_presets=project_presets,
                           global_presets=global_presets, total_chapters=total,
                           genre=_get_project_genre(name))
    return engine.get_status()


# ---- 全局审校引擎 ----

@router.post("/projects/{name}/review/start")
async def review_start(name: str, user=Depends(require_auth)):
    """启动全局审校。"""
    project_dir = get_project_dir(name)
    project_presets = _get_project_presets(name)
    global_presets = _get_global_presets()
    kg = KnowledgeGraph(project_dir)
    kg.load()

    engine = ReviewEngine(
        project_dir, name,
        project_presets=project_presets,
        global_presets=global_presets,
        kg=kg,
        genre=_get_project_genre(name),
    )
    return await engine.run_review()


@router.get("/projects/{name}/review/state")
def review_state(name: str):
    """获取审校引擎状态。"""
    project_dir = get_project_dir(name)
    project_presets = _get_project_presets(name)
    global_presets = _get_global_presets()

    engine = ReviewEngine(project_dir, name, project_presets=project_presets,
                          global_presets=global_presets,
                          genre=_get_project_genre(name))
    return engine.get_status()
