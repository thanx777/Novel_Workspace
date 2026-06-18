import os
import json
from typing import Optional

from fastapi import APIRouter, HTTPException

from project_db import get_project_dir, read_file_safe
from knowledge_graph import KnowledgeGraph
from memory_pipeline import IngestPipeline
from .schemas import OutlineNodeEditRequest

router = APIRouter()


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
    # 从 L2 章节细纲中提取该章信息
    l2_json_path = os.path.join(project_dir, "outline_L2.json")
    chapter_outline = {}
    if os.path.isfile(l2_json_path):
        try:
            with open(l2_json_path, "r", encoding="utf-8") as f:
                l2_data = json.load(f)
            chapters = l2_data.get("chapters", [])
            for ch in chapters:
                if ch.get("chapter_num") == chapter:
                    chapter_outline = ch
                    break
        except Exception:
            pass
    kg = KnowledgeGraph(project_dir)
    kg.load()
    ip = IngestPipeline(kg, project_dir)
    return await ip.ingest_chapter(chapter, text, l3=chapter_outline, characters_md=characters_md)


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
