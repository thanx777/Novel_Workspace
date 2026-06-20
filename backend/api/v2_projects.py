"""
v2 项目管理端点 — /api/v2/projects/{project_name}/...

这些端点从 main.py 迁移而来，补充 v2_router 中尚未覆盖的
项目 CRUD、预设、章节、记忆、阶段推进、迁移和文件访问功能。

注意：GET/POST /api/v2/projects 和 GET /api/v2/projects/{name}
已在 v2_router 的 projects.py 中实现，此处不重复。
"""
import os
import re
import time
import logging
from typing import Optional, List

from fastapi import APIRouter, HTTPException, Request, Depends
from pydantic import BaseModel

from .shared import limiter, safe_join
from .auth import require_auth
from project_db import (
    ProjectDB, delete_project, get_project_dir, get_project_file,
    write_file_safe,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["v2-projects"])


# ── Request models ───────────────────────────────────────────────────

class _ProjectPresets(BaseModel):
    manager: Optional[dict] = None
    worker: Optional[dict] = None
    reviewer: Optional[dict] = None
    chat: Optional[dict] = None


class _ProjectPatch(BaseModel):
    title: Optional[str] = None
    genre: Optional[str] = None
    total_chapters: Optional[int] = None
    outline_review_mode: Optional[str] = None
    word_count_min: Optional[int] = None
    word_count_max: Optional[int] = None
    max_rounds_writing: Optional[int] = None
    max_rounds_outline: Optional[int] = None


# ── Project CRUD ─────────────────────────────────────────────────────

@router.delete("/v2/projects/{project_name}")
@limiter.limit("60/minute")
def v2_delete_project(request: Request, project_name: str, user=Depends(require_auth)):
    """删除项目。"""
    try:
        ok = delete_project(project_name)
        return {"success": ok, "name": project_name}
    except Exception as e:
        logger.exception("v2_delete_project failed: %s", project_name)
        raise HTTPException(status_code=500, detail=str(e))


@router.patch("/v2/projects/{project_name}")
@limiter.limit("60/minute")
def v2_patch_project(request: Request, project_name: str, body: _ProjectPatch):
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


# ── Presets ──────────────────────────────────────────────────────────

@router.get("/v2/projects/{project_name}/presets")
@limiter.limit("60/minute")
def v2_get_project_presets(request: Request, project_name: str):
    """读取项目的三角色模型预设。"""
    try:
        db = ProjectDB(project_name)
        presets = db.get_presets()
        db.close()
        return {"presets": presets}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/v2/projects/{project_name}/presets")
@limiter.limit("60/minute")
def v2_update_project_presets(request: Request, project_name: str, body: _ProjectPresets):
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


# ── Chapters ─────────────────────────────────────────────────────────

@router.get("/v2/projects/{project_name}/chapters")
@limiter.limit("60/minute")
def v2_list_chapters(request: Request, project_name: str):
    """章节列表（侧边栏用）。"""
    try:
        db = ProjectDB(project_name)
        chapters = db.list_chapters()
        db.close()
        return {"chapters": chapters}
    except Exception as e:
        return {"chapters": [], "error": str(e)}


@router.get("/v2/projects/{project_name}/chapters/{chapter_index}")
@limiter.limit("60/minute")
def v2_get_chapter(request: Request, project_name: str, chapter_index: int):
    """读取单章正文。前端展示时清洗元数据标记，源文件保留。"""
    try:
        db = ProjectDB(project_name)
        chapter = db.get_chapter(chapter_index)
        db.close()
        if chapter is None:
            raise HTTPException(status_code=404, detail="Chapter not found")
        if chapter.get("content"):
            import re as _re
            chapter["content"] = _re.sub(r"^---(?:PREV|CAST|THREAD|STRAND)---\n?", "", chapter["content"], flags=_re.MULTILINE)
            chapter["content"] = _re.sub(r"\n{3,}", "\n\n", chapter["content"])
        return chapter
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.patch("/v2/projects/{project_name}/chapters/{chapter_index}")
@limiter.limit("60/minute")
def v2_update_chapter(request: Request, project_name: str, chapter_index: int, body: dict):
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


# ── Memory ───────────────────────────────────────────────────────────

@router.get("/v2/projects/{project_name}/memory")
@limiter.limit("60/minute")
def v2_list_memory(request: Request, project_name: str):
    """记忆条目列表。"""
    try:
        db = ProjectDB(project_name)
        items = db.list_memory()
        db.close()
        return {"memory": items}
    except Exception as e:
        return {"memory": [], "error": str(e)}


@router.post("/v2/projects/{project_name}/memory")
@limiter.limit("60/minute")
def v2_add_memory(request: Request, project_name: str, body: dict):
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


# ── Stage transitions ────────────────────────────────────────────────

@router.post("/v2/projects/{project_name}/confirm-outline")
@limiter.limit("60/minute")
def v2_confirm_outline(request: Request, project_name: str, user=Depends(require_auth)):
    """人工审查大纲后，推进到写作阶段。"""
    try:
        db = ProjectDB(project_name)
        db.update_project(current_stage="writing")
        data = db.to_dict()
        db.close()
        return {"success": True, "stage": "writing", "project": data}
    except Exception as e:
        logger.exception("v2_confirm_outline failed: %s", project_name)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/v2/projects/{project_name}/reject-outline")
@limiter.limit("60/minute")
def v2_reject_outline(request: Request, project_name: str):
    """审查不通过，停留在 outline 状态。"""
    try:
        db = ProjectDB(project_name)
        db.update_project(current_stage="outline")
        data = db.to_dict()
        db.close()
        return {"success": True, "stage": "outline", "project": data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/v2/projects/{project_name}/confirm-writing")
@limiter.limit("60/minute")
def v2_confirm_writing(request: Request, project_name: str, user=Depends(require_auth)):
    """写作完成后，推进到审校阶段。"""
    try:
        db = ProjectDB(project_name)
        db.update_project(current_stage="review")
        data = db.to_dict()
        db.close()
        return {"success": True, "stage": "review", "project": data}
    except Exception as e:
        logger.exception("v2_confirm_writing failed: %s", project_name)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/v2/projects/{project_name}/confirm-review")
@limiter.limit("60/minute")
def v2_confirm_review(request: Request, project_name: str, user=Depends(require_auth)):
    """审校完成，标记项目为已完成。"""
    try:
        db = ProjectDB(project_name)
        db.update_project(current_stage="done")
        data = db.to_dict()
        db.close()
        return {"success": True, "stage": "done", "project": data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── Migration ────────────────────────────────────────────────────────

@router.post("/v2/projects/migrate-old")
@limiter.limit("60/minute")
def v2_migrate_old_projects(request: Request, body: dict = {}):
    """迁移旧 run_* 目录到新项目系统。支持 dry-run。"""
    import subprocess
    dry = "1" if body.get("dry_run", False) else ""
    force = "1" if body.get("force", False) else ""
    cmd = ["python", os.path.join(os.path.dirname(os.path.dirname(__file__)), "migration.py")]
    if dry:
        cmd.append("--dry-run")
    if force:
        cmd.append("--force")
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120,
                                cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        return {
            "success": result.returncode == 0,
            "stdout": result.stdout,
            "stderr": result.stderr,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── Raw file access ──────────────────────────────────────────────────

@router.get("/v2/projects/{project_name}/file/{file_path:path}")
@limiter.limit("60/minute")
def v2_get_project_file(request: Request, project_name: str, file_path: str):
    """读取项目内任意文件（outline.md, characters.md 等）。"""
    try:
        project_dir = get_project_dir(project_name)
        full_path = safe_join(project_dir, file_path)
        if not os.path.exists(full_path):
            return {"path": file_path, "content": ""}
        with open(full_path, "r", encoding="utf-8") as f:
            content = f.read()
        if file_path.startswith("chapters/") and file_path.endswith(".txt"):
            import re as _re
            content = _re.sub(r"^---(?:PREV|CAST|THREAD|STRAND)---\n?", "", content, flags=_re.MULTILINE)
            content = _re.sub(r"\n{3,}", "\n\n", content)
        return {"path": file_path, "content": content}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/v2/projects/{project_name}/file/{file_path:path}")
@limiter.limit("60/minute")
def v2_put_project_file(request: Request, project_name: str, file_path: str, body: dict):
    """写入项目内任意文件。"""
    try:
        project_dir = get_project_dir(project_name)
        content = body.get("content", "")
        full_path = safe_join(project_dir, file_path)
        os.makedirs(os.path.dirname(full_path), exist_ok=True)
        with open(full_path, "w", encoding="utf-8") as f:
            f.write(content)
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
