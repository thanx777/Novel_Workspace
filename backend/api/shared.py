"""
Shared utilities and singletons for API sub-modules.

Centralises the slowapi limiter, workspace/project directory globals,
path-safety helpers, and config.json read/write so every router can
import from one place instead of depending on main.py.
"""
import json
import os

from fastapi import HTTPException
from slowapi import Limiter
from slowapi.util import get_remote_address

import paths

# ── Rate limiter (single instance shared by all routers) ──────────────
limiter = Limiter(key_func=get_remote_address)

# ── Workspace / Projects directories (mutable globals) ───────────────
from project_db import WORKSPACE_DIR as _PDB_WS, PROJECTS_DIR as _PDB_PJ

WORKSPACE_DIR = _PDB_WS
PROJECTS_DIR = _PDB_PJ


def _resolve_workspace_dir(path: str, default_name: str) -> str:
    """Resolve workspace/projects directory path."""
    if path and path.strip():
        return os.path.abspath(path.strip())
    return paths.get_data_root()


def get_full_path(filename: str) -> str:
    """Get full path for a workspace file, with path traversal protection."""
    full = os.path.abspath(os.path.join(WORKSPACE_DIR, filename))
    if not full.startswith(os.path.abspath(WORKSPACE_DIR)):
        raise HTTPException(status_code=400, detail="Invalid path")
    return full


def safe_join(root: str, *paths: str) -> str:
    """安全拼接路径，防止路径穿越。返回的绝对路径必须在 root 内。"""
    root_abs = os.path.abspath(root)
    full = os.path.abspath(os.path.join(root_abs, *paths))
    if not full.startswith(root_abs + os.sep) and full != root_abs:
        raise HTTPException(status_code=400, detail="Invalid path")
    return full


# ── config.json helpers ──────────────────────────────────────────────

def _get_config_path() -> str:
    return paths.get_config_path()


def _read_config() -> dict:
    path = _get_config_path()
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"presets": []}


def _write_config(data: dict) -> None:
    config_path = _get_config_path()
    os.makedirs(os.path.dirname(config_path), exist_ok=True)
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
