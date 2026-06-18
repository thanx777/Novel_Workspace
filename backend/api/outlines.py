import os
import json

from fastapi import APIRouter, HTTPException

from project_db import ProjectDB, get_project_dir, read_file_safe
from outline_templates import LAYER_NAMES
from knowledge_graph import KnowledgeGraph
from engines.common.state import EngineState
from engines.outline.engine import OutlineEngine
from .schemas import OutlineLayersRequest
from .engine_registry import _get_project_presets, _get_project_genre, _get_global_presets

router = APIRouter()


@router.put("/projects/{name}/outline-layers")
def update_outline_layers(name: str, req: OutlineLayersRequest):
    db = ProjectDB(name)
    layers = req.layers
    # 校验：L1 关则 L2 不能开
    if not layers.get("L1", True):
        layers["L2"] = False
    db.set_outline_layers(layers)
    # 同步到 EngineState（统一状态源）
    project_dir = get_project_dir(name)
    state = EngineState(project_dir)
    if not layers.get("L1", True):
        # L1 关闭时清除 L1 完成标记
        completed = state.data.get("outline", {}).get("completed_layers", [])
        state.data.setdefault("outline", {})["completed_layers"] = [l for l in completed if l != "L1"]
        state.save()
    if not layers.get("L2", True):
        completed = state.data.get("outline", {}).get("completed_layers", [])
        state.data.setdefault("outline", {})["completed_layers"] = [l for l in completed if l != "L2"]
        state.save()
    return {"success": True, "outline_layers": db.get_outline_layers()}


# ============================================================
# 大纲分层 API
# ============================================================

@router.get("/projects/{name}/outlines")
def list_outlines(name: str):
    project_dir = get_project_dir(name)
    # 使用 EngineState 统一状态源，不再依赖 OutlinePipeline 的 outline_state.json
    state = EngineState(project_dir)
    outline_state = state.data.get("outline", {})
    completed_layers = outline_state.get("completed_layers", [])
    result = {}
    for layer in ("L1", "L2"):
        md_path = os.path.join(project_dir, f"outline_{layer}.md")
        json_path = os.path.join(project_dir, f"outline_{layer}.json")
        exists = os.path.isfile(md_path) and os.path.isfile(json_path)
        result[layer] = {
            "enabled": True,
            "exists": exists,
            "md_path": md_path,
            "json_path": json_path,
            "generated_at": None,
            "name": LAYER_NAMES[layer],
            "completed": layer in completed_layers,
        }
    result["state"] = outline_state.get("status", "pending")
    return result


@router.get("/projects/{name}/outlines/{layer}")
def get_outline(name: str, layer: str):
    if layer not in ("L1", "L2"):
        raise HTTPException(400, f"Unknown layer: {layer}")
    project_dir = get_project_dir(name)
    md_path = os.path.join(project_dir, f"outline_{layer}.md")
    json_path = os.path.join(project_dir, f"outline_{layer}.json")
    return {
        "layer": layer,
        "name": LAYER_NAMES[layer],
        "md": read_file_safe(md_path, ""),
        "json_data": json.loads(read_file_safe(json_path, "{}")) if os.path.isfile(json_path) else {},
    }


@router.post("/projects/{name}/outlines/{layer}/regenerate")
async def regenerate_outline(name: str, layer: str):
    if layer not in ("L1", "L2"):
        raise HTTPException(400, f"Unknown layer: {layer}")
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
    # 重置该层完成状态，允许重新生成
    completed = engine.state.data.get("outline", {}).get("completed_layers", [])
    if layer in completed:
        completed.remove(layer)
        engine.state.data.setdefault("outline", {})["completed_layers"] = completed
        engine.state.save()
    return await engine.generate_layer(layer)


@router.post("/projects/{name}/outlines/bootstrap")
async def bootstrap_outlines(name: str, requirements: str = ""):
    """一键生成 L1→L2。"""
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
    return await engine.generate_all(requirements=requirements)
