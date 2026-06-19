import os
import time

from fastapi import APIRouter, HTTPException, Depends

from project_db import ProjectDB, get_project_dir, list_all_projects
from knowledge_graph import KnowledgeGraph
from .schemas import ProjectCreateRequest
from .auth import require_auth

router = APIRouter()


# ============================================================
# 项目端点（已含 outline_layers）
# ============================================================

@router.get("/projects")
def list_projects():
    return {"projects": list_all_projects()}


@router.get("/projects/{name}")
def get_project(name: str):
    try:
        db = ProjectDB(name)
        info = db.get_project()
        info["outline_layers"] = db.get_outline_layers()
        # 合并进度数据，让前端能获取 chapters_done 和 total_words
        progress = db.get_progress()
        info["chapters_done"] = progress.get("done", 0)
        info["total_words"] = progress.get("total_words", 0)
        return info
    except Exception as e:
        raise HTTPException(404, f"Project not found: {e}")


@router.post("/projects")
def create_project(req: ProjectCreateRequest, user=Depends(require_auth)):
    from project_db import create_project as _cp
    try:
        result = _cp(
            name=req.name or f"project_{int(time.time())}",
            title=req.title or req.name,
            genre=req.genre,
            total_chapters=req.total_chapters,
            outline_review_mode="auto",
            outline_layers=req.outline_layers,
        )
    except Exception as e:
        raise HTTPException(400, f"Create failed: {e}")
    db = ProjectDB(req.name)
    if req.outline_layers:
        db.set_outline_layers(req.outline_layers)
    # 保存章节字数配置
    db.update_project(word_count_min=req.word_count_min, word_count_max=req.word_count_max,
                       max_rounds_writing=req.max_rounds_writing, max_rounds_outline=req.max_rounds_outline)
    # 保存角色预设
    if req.role_presets:
        db.set_presets(
            manager=req.role_presets.get("manager"),
            worker=req.role_presets.get("worker"),
            reviewer=req.role_presets.get("reviewer"),
            chat=req.role_presets.get("chat"),
        )
    # 保存附加要求到文件
    if req.extra_requirements:
        project_dir = get_project_dir(req.name)
        req_path = os.path.join(project_dir, "extra_requirements.txt")
        with open(req_path, "w", encoding="utf-8") as f:
            f.write(req.extra_requirements)
    # bootstrap knowledge graph
    project_dir = get_project_dir(req.name)
    kg = KnowledgeGraph(project_dir)
    kg.load()
    return {"success": True, "project": db.get_project(), "outline_layers": db.get_outline_layers()}
