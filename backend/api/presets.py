"""
预设管理 — /api/presets, /api/presets/default
"""
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from .shared import limiter, _read_config, _write_config

router = APIRouter(prefix="/api", tags=["presets"])


# ── Request models ───────────────────────────────────────────────────

class PresetCreate(BaseModel):
    name: str
    base_url: str
    model: str
    api_key: str
    api_format: str = "openai"
    thinking_mode: Optional[str] = None


class PresetUpdate(BaseModel):
    original_name: str
    name: str
    base_url: str
    model: str
    api_key: str
    api_format: str = "openai"
    thinking_mode: Optional[str] = None


# ── Endpoints ────────────────────────────────────────────────────────

@router.get("/presets")
@limiter.limit("60/minute")
def get_presets(request: Request):
    import json, os
    config_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "config.json")
    if os.path.exists(config_path):
        with open(config_path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"presets": []}


@router.post("/presets")
@limiter.limit("60/minute")
def add_preset(request: Request, preset: PresetCreate):
    data = _read_config()
    if "presets" not in data:
        data["presets"] = []
    data["presets"].append(preset.model_dump())
    _write_config(data)
    return data


@router.delete("/presets")
@limiter.limit("60/minute")
def delete_preset(request: Request, name: str):
    data = _read_config()
    if "presets" not in data:
        data["presets"] = []
    data["presets"] = [p for p in data["presets"] if p.get("name") != name]
    _write_config(data)
    return data


@router.put("/presets")
@limiter.limit("60/minute")
def update_preset(request: Request, preset: PresetUpdate):
    data = _read_config()
    if "presets" not in data:
        data["presets"] = []
    for i, p in enumerate(data["presets"]):
        if p.get("name") == preset.original_name:
            data["presets"][i] = preset.model_dump(exclude={"original_name"})
            _write_config(data)
            return data
    raise HTTPException(status_code=404, detail="Preset not found")


@router.put("/presets/default")
@limiter.limit("60/minute")
def set_default_preset(request: Request, name: str):
    """设置默认预设（新项目自动使用此预设）。"""
    data = _read_config()
    found = any(p.get("name") == name for p in data.get("presets", []))
    if not found:
        raise HTTPException(status_code=404, detail="Preset not found")
    data["default_preset"] = name
    _write_config(data)
    return data


@router.delete("/presets/default")
@limiter.limit("60/minute")
def clear_default_preset(request: Request):
    """清除默认预设。"""
    data = _read_config()
    data.pop("default_preset", None)
    _write_config(data)
    return data
