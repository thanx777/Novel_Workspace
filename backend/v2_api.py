"""
v2 API 模块：分层大纲 + 知识图谱的 API 端点
设计为 FastAPI router，可被 main.py 直接 include。
"""
import os
import json
import asyncio
from typing import List, Dict, Optional, Any

from fastapi import APIRouter, HTTPException, Body
from pydantic import BaseModel

# 复用项目已有路径
from project_db import (
    ProjectDB, get_project_dir, read_file_safe, write_file_safe, list_all_projects,
)
from outline_templates import parse_markdown_to_json, validate_template, LAYER_NAMES
from outline_pipeline import OutlinePipeline
from knowledge_graph import KnowledgeGraph, NODE_COLORS, LAYER_COLORS
from memory_pipeline import IngestPipeline

router = APIRouter(prefix="/api/v2", tags=["v2"])


# ============================================================
# 数据模型
# ============================================================

class ProjectCreateRequest(BaseModel):
    name: str
    title: str = ""
    genre: str = ""
    total_chapters: int = 100
    description: str = ""
    outline_layers: Optional[Dict[str, bool]] = None  # {"L1": true, "L2": true, "L3": true}


class OutlineLayersRequest(BaseModel):
    layers: Dict[str, bool]


class OutlineNodeEditRequest(BaseModel):
    label: Optional[str] = None
    summary: Optional[str] = None
    attrs: Optional[Dict[str, Any]] = None


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
        return info
    except Exception as e:
        raise HTTPException(404, f"Project not found: {e}")


@router.post("/projects")
def create_project(req: ProjectCreateRequest):
    from project_db import create_project as _cp
    try:
        result = _cp(
            name=req.name or f"project_{int(time.time())}",
            title=req.title or req.name,
            genre=req.genre,
            total_chapters=req.total_chapters,
            execution_mode="lite",
            outline_review_mode="auto",
            outline_layers=req.outline_layers,
        )
    except Exception as e:
        raise HTTPException(400, f"Create failed: {e}")
    db = ProjectDB(req.name)
    if req.outline_layers:
        db.set_outline_layers(req.outline_layers)
    # bootstrap knowledge graph
    project_dir = get_project_dir(req.name)
    kg = KnowledgeGraph(project_dir)
    kg.load()
    return {"success": True, "project": db.get_project(), "outline_layers": db.get_outline_layers()}


@router.put("/projects/{name}/outline-layers")
def update_outline_layers(name: str, req: OutlineLayersRequest):
    db = ProjectDB(name)
    layers = req.layers
    # 校验：L1 关则 L2/L3 不能开
    if not layers.get("L1", True):
        layers["L2"] = False
        layers["L3"] = False
    elif not layers.get("L2", True):
        # L2 关不影响 L1/L3
        pass
    db.set_outline_layers(layers)
    # 同步到 outline_pipeline 状态
    project_dir = get_project_dir(name)
    op = OutlinePipeline(project_dir, name)
    op.set_layers_enabled(layers)
    return {"success": True, "outline_layers": db.get_outline_layers()}


# ============================================================
# 大纲分层 API
# ============================================================

@router.get("/projects/{name}/outlines")
def list_outlines(name: str):
    project_dir = get_project_dir(name)
    op = OutlinePipeline(project_dir, name)
    op.kg.load()
    return op.get_status()


@router.get("/projects/{name}/outlines/{layer}")
def get_outline(name: str, layer: str, chapter: Optional[int] = None):
    if layer not in ("L1", "L2", "L3"):
        raise HTTPException(400, f"Unknown layer: {layer}")
    project_dir = get_project_dir(name)
    if layer in ("L1", "L2"):
        md_path = os.path.join(project_dir, f"outline_{layer}.md")
        json_path = os.path.join(project_dir, f"outline_{layer}.json")
        return {
            "layer": layer,
            "name": LAYER_NAMES[layer],
            "md": read_file_safe(md_path, ""),
            "json_data": json.loads(read_file_safe(json_path, "{}")) if os.path.isfile(json_path) else {},
        }
    # L3
    if chapter is None:
        raise HTTPException(400, "L3 需要指定 ?chapter=N")
    md_path = os.path.join(project_dir, "outline_L3", f"chapter_{chapter}.md")
    json_path = os.path.join(project_dir, "outline_L3", f"chapter_{chapter}.json")
    if not os.path.isfile(md_path):
        raise HTTPException(404, f"第 {chapter} 章细纲不存在")
    return {
        "layer": "L3",
        "chapter": chapter,
        "name": f"L3 第{chapter}章细纲",
        "md": read_file_safe(md_path, ""),
        "json_data": json.loads(read_file_safe(json_path, "{}")) if os.path.isfile(json_path) else {},
    }


@router.post("/projects/{name}/outlines/{layer}/regenerate")
async def regenerate_outline(name: str, layer: str, chapter: Optional[int] = None):
    project_dir = get_project_dir(name)
    db = ProjectDB(name)
    presets_list = list(db.get_presets().values())
    op = OutlinePipeline(project_dir, name, presets=presets_list)
    if layer == "L3" and chapter is not None:
        return await op.regenerate("L3", chapter=chapter)
    return await op.regenerate(layer)


@router.post("/projects/{name}/outlines/bootstrap")
async def bootstrap_outlines(name: str, requirements: str = ""):
    """一键生成 L1→L2。"""
    project_dir = get_project_dir(name)
    db = ProjectDB(name)
    presets_list = list(db.get_presets().values())
    op = OutlinePipeline(project_dir, name, presets=presets_list)
    return await op.bootstrap_l1_l2(requirements=requirements)


# ============================================================
# 知识图谱 API
# ============================================================

@router.get("/projects/{name}/graph")
def get_graph(name: str, type: Optional[str] = None):
    project_dir = get_project_dir(name)
    kg = KnowledgeGraph(project_dir)
    kg.load()
    nodes = kg.list_nodes(type_=type)
    return {
        "nodes": nodes,
        "edges": list(kg.edges.values()),
        "stats": kg.stats(),
    }


@router.get("/projects/{name}/graph/stats")
def get_graph_stats(name: str):
    project_dir = get_project_dir(name)
    kg = KnowledgeGraph(project_dir)
    kg.load()
    return kg.stats()


@router.get("/projects/{name}/graph/context")
def get_graph_context(name: str, chapter: int):
    project_dir = get_project_dir(name)
    kg = KnowledgeGraph(project_dir)
    kg.load()
    return kg.query_context(chapter)


@router.post("/projects/{name}/graph/ingest/{chapter}")
async def manual_ingest(name: str, chapter: int):
    """手动触发某章的图谱摄取。"""
    project_dir = get_project_dir(name)
    chapter_path = os.path.join(project_dir, "chapters", f"第{chapter}章.txt")
    if not os.path.isfile(chapter_path):
        raise HTTPException(404, f"章节文件不存在：{chapter_path}")
    text = read_file_safe(chapter_path, "")
    characters_md = read_file_safe(os.path.join(project_dir, "characters.md"), "")
    l3_path = os.path.join(project_dir, "outline_L3", f"chapter_{chapter}.json")
    l3 = json.loads(read_file_safe(l3_path, "{}")) if os.path.isfile(l3_path) else {}
    kg = KnowledgeGraph(project_dir)
    kg.load()
    ip = IngestPipeline(kg, project_dir)
    return await ip.ingest_chapter(chapter, text, l3=l3, characters_md=characters_md)


@router.put("/projects/{name}/graph/node/{node_id}")
def edit_node(name: str, node_id: str, req: OutlineNodeEditRequest):
    project_dir = get_project_dir(name)
    kg = KnowledgeGraph(project_dir)
    kg.load()
    node = kg.update_node(node_id, label=req.label, summary=req.summary, attrs=req.attrs)
    if not node:
        raise HTTPException(404, f"Node {node_id} 不存在")
    kg.save()
    return {"success": True, "node": node}


@router.delete("/projects/{name}/graph/node/{node_id}")
def delete_node(name: str, node_id: str):
    project_dir = get_project_dir(name)
    kg = KnowledgeGraph(project_dir)
    kg.load()
    if not kg.delete_node(node_id):
        raise HTTPException(404, f"Node {node_id} 不存在")
    kg.save()
    return {"success": True}


@router.get("/projects/{name}/graph/markdown-view")
def graph_markdown_view(name: str):
    """导出图谱为 markdown 人读视图。"""
    project_dir = get_project_dir(name)
    kg = KnowledgeGraph(project_dir)
    kg.load()
    return {"markdown": kg.export_markdown_view()}


# ============================================================
# 旧 memory.md 迁移 API
# ============================================================

@router.post("/projects/{name}/graph/bootstrap-from-markdown")
def bootstrap_from_markdown(name: str):
    project_dir = get_project_dir(name)
    kg = KnowledgeGraph(project_dir)
    kg.load()
    memory_path = os.path.join(project_dir, "memory", "novel_memory.md")
    chars_path = os.path.join(project_dir, "characters.md")
    outline_path = os.path.join(project_dir, "outline.md")
    added = kg.bootstrap_from_markdown(memory_path, chars_path, outline_path)
    return {"success": True, "added_nodes": added}
