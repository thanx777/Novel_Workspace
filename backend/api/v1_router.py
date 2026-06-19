"""
v1 项目 CRUD — @deprecated

这些端点操作 projects/ 目录下的 JSON 文件，已被 v2 项目系统取代。
保留仅为向后兼容。
"""
import json
import os
import re

from fastapi import APIRouter, HTTPException, Request

from .shared import limiter, PROJECTS_DIR

router = APIRouter(prefix="/api", tags=["v1-projects"])


@router.get("/projects")
@limiter.limit("60/minute")
def list_projects(request: Request):
    """@deprecated 使用 /api/v2/projects 代替。"""
    projects = []
    if os.path.isdir(PROJECTS_DIR):
        for f in sorted(os.listdir(PROJECTS_DIR)):
            if f.endswith(".json"):
                projects.append({"filename": f, "name": f.replace(".json", "")})
    return {"projects": projects}


@router.post("/projects")
@limiter.limit("60/minute")
def save_project(request: Request, project: dict):
    """@deprecated 使用 /api/v2/projects 代替。"""
    name = project.get("name", "untitled")
    filename = re.sub(r'[<>:"/\\|?*]', "_", name) + ".json"
    path = os.path.join(PROJECTS_DIR, filename)
    os.makedirs(PROJECTS_DIR, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(project, f, ensure_ascii=False, indent=2)
    return {"status": "success", "filename": filename}


@router.get("/projects/{filename}")
@limiter.limit("60/minute")
def load_project(request: Request, filename: str):
    """@deprecated 使用 /api/v2/projects/{name} 代替。"""
    if ".." in filename or "/" in filename or "\\" in filename:
        raise HTTPException(status_code=400, detail="Invalid filename")
    filepath = os.path.join(PROJECTS_DIR, filename)
    if not os.path.exists(filepath):
        raise HTTPException(status_code=404, detail="Project not found")
    with open(filepath, "r", encoding="utf-8") as f:
        return json.load(f)


@router.delete("/projects/{filename}")
@limiter.limit("60/minute")
def delete_project(request: Request, filename: str):
    """@deprecated 使用 /api/v2/projects/{name} 代替。"""
    if ".." in filename or "/" in filename or "\\" in filename:
        raise HTTPException(status_code=400, detail="Invalid filename")
    filepath = os.path.join(PROJECTS_DIR, filename)
    if os.path.exists(filepath):
        os.remove(filepath)
        return {"status": "success"}
    raise HTTPException(status_code=404, detail="Project not found")
