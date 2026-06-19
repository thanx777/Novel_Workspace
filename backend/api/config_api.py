"""
配置管理 — /api/workspace-config, /api/workspace/config
"""
import os

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

import paths
from .shared import (
    limiter, WORKSPACE_DIR, PROJECTS_DIR,
    _read_config, _write_config, _resolve_workspace_dir,
)

router = APIRouter(prefix="/api", tags=["config"])


# ── Request models ───────────────────────────────────────────────────

class WorkspaceConfig(BaseModel):
    path: str


class WorkspaceConfigModel(BaseModel):
    workspace_dir: str = ""
    projects_dir: str = ""


# ── Endpoints ────────────────────────────────────────────────────────

@router.get("/workspace-config")
@limiter.limit("60/minute")
def get_workspace_config(request: Request):
    data = _read_config()
    return {
        "workspace_dir": data.get("workspace_dir", ""),
        "projects_dir": data.get("projects_dir", ""),
        "current_workspace": WORKSPACE_DIR,
        "current_projects": PROJECTS_DIR,
        "default_workspace": paths.get_data_root(),
        "default_projects": os.path.join(paths.get_data_root(), "projects"),
    }


@router.put("/workspace-config")
@limiter.limit("60/minute")
def update_workspace_config(request: Request, cfg: WorkspaceConfigModel):
    from . import shared as _shared
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

    _shared.WORKSPACE_DIR = _resolve_workspace_dir(new_ws, "workspace")
    _shared.PROJECTS_DIR = _resolve_workspace_dir(new_pj, "projects")

    return {
        "status": "success",
        "workspace_dir": _shared.WORKSPACE_DIR,
        "projects_dir": _shared.PROJECTS_DIR,
    }


@router.get("/workspace/config")
@limiter.limit("60/minute")
def get_workspace(request: Request):
    return WorkspaceConfig(path=WORKSPACE_DIR)


@router.post("/workspace/config")
@limiter.limit("60/minute")
def set_workspace(request: Request, config: WorkspaceConfig):
    from . import shared as _shared
    _shared.WORKSPACE_DIR = config.path
    os.makedirs(_shared.WORKSPACE_DIR, exist_ok=True)
    return {"status": "success"}
