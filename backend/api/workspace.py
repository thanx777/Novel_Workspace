"""
文件操作 — /api/workspace/files, /api/workspace/folders
"""
import os
from typing import List

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from .shared import limiter, WORKSPACE_DIR, get_full_path, safe_join

router = APIRouter(prefix="/api", tags=["workspace"])


# ── Request models ───────────────────────────────────────────────────

class FileContent(BaseModel):
    content: str


class FolderStructure(BaseModel):
    folders: List[str]


# ── Endpoints ────────────────────────────────────────────────────────

@router.get("/workspace/files")
@limiter.limit("60/minute")
def list_files(request: Request, folder: str = ""):
    target_dir = safe_join(WORKSPACE_DIR, folder) if folder else os.path.abspath(WORKSPACE_DIR)
    if not os.path.isdir(target_dir):
        return {"files": [], "folder": folder}
    files = []
    for f in sorted(os.listdir(target_dir)):
        full = os.path.join(target_dir, f)
        if os.path.isfile(full):
            files.append(f)
    return {"files": files, "folder": folder}


@router.post("/workspace/folders")
@limiter.limit("60/minute")
def create_folders(request: Request, structure: FolderStructure):
    for folder in structure.folders:
        target = safe_join(WORKSPACE_DIR, folder)
        os.makedirs(target, exist_ok=True)
    return {"status": "success"}


@router.get("/workspace/files/{filename:path}")
@limiter.limit("60/minute")
def get_file(request: Request, filename: str):
    path = get_full_path(filename)
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="File not found")
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        return {"content": f.read(), "filename": filename}


@router.post("/workspace/files/{filename:path}")
@limiter.limit("60/minute")
def save_file(request: Request, filename: str, body: FileContent):
    path = get_full_path(filename)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(body.content)
    return {"status": "success", "filename": filename}


@router.delete("/workspace/files/{filename:path}")
@limiter.limit("60/minute")
def delete_file(request: Request, filename: str):
    path = get_full_path(filename)
    if os.path.exists(path):
        os.remove(path)
        return {"status": "success"}
    raise HTTPException(status_code=404, detail="File not found")
