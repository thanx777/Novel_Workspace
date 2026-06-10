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
from sse_starlette.sse import EventSourceResponse

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


# ============================================================
# 引擎 API — 大纲/写作/审校三阶段
# ============================================================

from engines.outline.engine import OutlineEngine
from engines.writing.engine import WritingEngine
from engines.review.engine import ReviewEngine


def _get_project_presets(name: str) -> Dict:
    """获取项目级角色预设。"""
    try:
        db = ProjectDB(name)
        return db.get_presets()
    except Exception:
        return {}


def _get_project_genre(name: str) -> str:
    """获取项目体裁。"""
    try:
        db = ProjectDB(name)
        return db.get_project().get("genre", "")
    except Exception:
        return ""


def _get_global_presets() -> List[Dict]:
    """获取全局预设列表。"""
    try:
        state_path = os.path.join(os.path.dirname(__file__), "state.json")
        if os.path.isfile(state_path):
            with open(state_path, "r", encoding="utf-8") as f:
                state = json.load(f)
            presets = state.get("presets", {})
            if isinstance(presets, dict):
                return list(presets.values())
            elif isinstance(presets, list):
                return presets
    except Exception:
        pass
    return []


class EngineChatRequest(BaseModel):
    message: str
    layer: str = ""
    chapter: int = 0


class OutlineGenerateRequest(BaseModel):
    layer: str = ""
    requirements: str = ""


class WritingStartRequest(BaseModel):
    start_chapter: int = 1
    total_chapters: int = 0


# ---- 引擎全局状态 ----

@router.get("/projects/{name}/engine/state")
def get_engine_state(name: str):
    """获取引擎全局状态（当前阶段、进度）。"""
    project_dir = get_project_dir(name)
    from engines.common.state import EngineState
    state = EngineState(project_dir)
    return state.data


# ---- 大纲引擎 ----

@router.post("/projects/{name}/outline/generate")
async def outline_generate(name: str, req: OutlineGenerateRequest):
    """触发大纲 MWR 循环生成。"""
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

    if req.layer:
        return await engine.generate_layer(req.layer, requirements=req.requirements)
    else:
        return await engine.generate_all(requirements=req.requirements)


@router.get("/projects/{name}/outline/state")
def outline_state(name: str):
    """获取大纲引擎状态。"""
    project_dir = get_project_dir(name)
    project_presets = _get_project_presets(name)
    global_presets = _get_global_presets()
    engine = OutlineEngine(project_dir, name, project_presets=project_presets, global_presets=global_presets,
                           genre=_get_project_genre(name))
    return engine.get_status()


@router.post("/projects/{name}/outline/chat")
async def outline_chat(name: str, req: EngineChatRequest):
    """大纲 AI 对话。"""
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
    response = await engine.chat(req.message, layer=req.layer)
    return {"response": response}


# ---- 写作引擎 ----

@router.post("/projects/{name}/writing/start")
async def writing_start(name: str, req: WritingStartRequest):
    """启动写作引擎。"""
    project_dir = get_project_dir(name)
    db = ProjectDB(name)
    project_presets = db.get_presets()
    global_presets = _get_global_presets()
    kg = KnowledgeGraph(project_dir)
    kg.load()

    total = req.total_chapters or db.get_project().get("total_chapters", 100)

    engine = WritingEngine(
        project_dir, name,
        project_presets=project_presets,
        global_presets=global_presets,
        kg=kg,
        total_chapters=total,
        genre=_get_project_genre(name),
    )

    if req.start_chapter > 1:
        return await engine.write_chapter(req.start_chapter)
    else:
        return await engine.write_all(start_chapter=req.start_chapter)


@router.get("/projects/{name}/writing/state")
def writing_state(name: str):
    """获取写作引擎状态。"""
    project_dir = get_project_dir(name)
    db = ProjectDB(name)
    project_presets = db.get_presets()
    global_presets = _get_global_presets()

    total = db.get_project().get("total_chapters", 100)
    engine = WritingEngine(project_dir, name, project_presets=project_presets,
                           global_presets=global_presets, total_chapters=total,
                           genre=_get_project_genre(name))
    return engine.get_status()


@router.post("/projects/{name}/writing/chat")
async def writing_chat(name: str, req: EngineChatRequest):
    """写作 AI 对话。"""
    project_dir = get_project_dir(name)
    project_presets = _get_project_presets(name)
    global_presets = _get_global_presets()
    kg = KnowledgeGraph(project_dir)
    kg.load()

    engine = WritingEngine(
        project_dir, name,
        project_presets=project_presets,
        global_presets=global_presets,
        kg=kg,
        genre=_get_project_genre(name),
    )
    response = await engine.chat(req.message, chapter_num=req.chapter)
    return {"response": response}


# ---- 全局审校引擎 ----

@router.post("/projects/{name}/review/start")
async def review_start(name: str):
    """启动全局审校。"""
    project_dir = get_project_dir(name)
    project_presets = _get_project_presets(name)
    global_presets = _get_global_presets()
    kg = KnowledgeGraph(project_dir)
    kg.load()

    engine = ReviewEngine(
        project_dir, name,
        project_presets=project_presets,
        global_presets=global_presets,
        kg=kg,
        genre=_get_project_genre(name),
    )
    return await engine.run_review()


@router.get("/projects/{name}/review/state")
def review_state(name: str):
    """获取审校引擎状态。"""
    project_dir = get_project_dir(name)
    project_presets = _get_project_presets(name)
    global_presets = _get_global_presets()

    engine = ReviewEngine(project_dir, name, project_presets=project_presets,
                          global_presets=global_presets,
                          genre=_get_project_genre(name))
    return engine.get_status()


# ---- SSE 流式引擎端点（日志实时推送） ----

@router.post("/projects/{name}/outline/generate/stream")
async def outline_generate_stream(name: str, req: OutlineGenerateRequest):
    """大纲 MWR 循环生成（SSE 流式，实时推送进度日志）。"""
    return EventSourceResponse(_outline_generate_stream(name, req))


async def _outline_generate_stream(name: str, req: OutlineGenerateRequest):
    project_dir = get_project_dir(name)
    project_presets = _get_project_presets(name)
    global_presets = _get_global_presets()
    kg = KnowledgeGraph(project_dir)
    kg.load()

    q = asyncio.Queue()

    def q_emit(data):
        try:
            q.put_nowait(data)
        except Exception:
            pass

    engine = OutlineEngine(
        project_dir, name,
        project_presets=project_presets,
        global_presets=global_presets,
        kg=kg,
        genre=_get_project_genre(name),
        yield_func=q_emit,
    )

    q_emit({"status": "start", "stage": "outline", "message": "🚀 开始大纲生成"})

    exec_task = asyncio.create_task(
        engine.generate_all(requirements=req.requirements) if not req.layer
        else engine.generate_layer(req.layer, requirements=req.requirements)
    )

    try:
        while True:
            try:
                msg = await asyncio.wait_for(q.get(), timeout=0.5)
                yield {"data": json.dumps(msg, ensure_ascii=False)}
            except asyncio.TimeoutError:
                if exec_task.done():
                    while not q.empty():
                        try:
                            msg = q.get_nowait()
                            yield {"data": json.dumps(msg, ensure_ascii=False)}
                        except asyncio.QueueEmpty:
                            break
                    break

        result = await exec_task
        # Sync project.db current_stage with engine_state
        try:
            db = ProjectDB(name)
            engine_state = EngineState(project_dir)
            db.set_stage(engine_state.current_stage)
            db.close()
        except Exception:
            pass
        yield {"data": json.dumps({"status": "done", "stage": "outline", "result": str(result)[:500]}, ensure_ascii=False)}
    except Exception as e:
        yield {"data": json.dumps({"status": "error", "message": str(e)}, ensure_ascii=False)}


@router.post("/projects/{name}/writing/start/stream")
async def writing_start_stream(name: str, req: WritingStartRequest):
    """写作引擎（SSE 流式，实时推送进度日志）。"""
    return EventSourceResponse(_writing_start_stream(name, req))


async def _writing_start_stream(name: str, req: WritingStartRequest):
    project_dir = get_project_dir(name)
    db = ProjectDB(name)
    project_presets = db.get_presets()
    global_presets = _get_global_presets()
    kg = KnowledgeGraph(project_dir)
    kg.load()

    total = req.total_chapters or db.get_project().get("total_chapters", 100)

    q = asyncio.Queue()

    def q_emit(data):
        try:
            q.put_nowait(data)
        except Exception:
            pass

    engine = WritingEngine(
        project_dir, name,
        project_presets=project_presets,
        global_presets=global_presets,
        kg=kg,
        total_chapters=total,
        genre=_get_project_genre(name),
        yield_func=q_emit,
    )

    q_emit({"status": "start", "stage": "writing", "message": "🚀 开始写作"})

    exec_task = asyncio.create_task(
        engine.write_chapter(req.start_chapter) if req.start_chapter > 1
        else engine.write_all(start_chapter=req.start_chapter)
    )

    try:
        while True:
            try:
                msg = await asyncio.wait_for(q.get(), timeout=0.5)
                yield {"data": json.dumps(msg, ensure_ascii=False)}
            except asyncio.TimeoutError:
                if exec_task.done():
                    while not q.empty():
                        try:
                            msg = q.get_nowait()
                            yield {"data": json.dumps(msg, ensure_ascii=False)}
                        except asyncio.QueueEmpty:
                            break
                    break

        result = await exec_task
        # Sync project.db current_stage with engine_state
        try:
            db = ProjectDB(name)
            engine_state = EngineState(project_dir)
            db.set_stage(engine_state.current_stage)
            db.close()
        except Exception:
            pass
        yield {"data": json.dumps({"status": "done", "stage": "writing", "result": str(result)[:500]}, ensure_ascii=False)}
    except Exception as e:
        yield {"data": json.dumps({"status": "error", "message": str(e)}, ensure_ascii=False)}


@router.post("/projects/{name}/review/start/stream")
async def review_start_stream(name: str):
    """全局审校引擎（SSE 流式，实时推送进度日志）。"""
    return EventSourceResponse(_review_start_stream(name))


async def _review_start_stream(name: str):
    project_dir = get_project_dir(name)
    project_presets = _get_project_presets(name)
    global_presets = _get_global_presets()
    kg = KnowledgeGraph(project_dir)
    kg.load()

    q = asyncio.Queue()

    def q_emit(data):
        try:
            q.put_nowait(data)
        except Exception:
            pass

    engine = ReviewEngine(
        project_dir, name,
        project_presets=project_presets,
        global_presets=global_presets,
        kg=kg,
        genre=_get_project_genre(name),
        yield_func=q_emit,
    )

    q_emit({"status": "start", "stage": "review", "message": "🚀 开始全局审校"})

    exec_task = asyncio.create_task(engine.run_review())

    try:
        while True:
            try:
                msg = await asyncio.wait_for(q.get(), timeout=0.5)
                yield {"data": json.dumps(msg, ensure_ascii=False)}
            except asyncio.TimeoutError:
                if exec_task.done():
                    while not q.empty():
                        try:
                            msg = q.get_nowait()
                            yield {"data": json.dumps(msg, ensure_ascii=False)}
                        except asyncio.QueueEmpty:
                            break
                    break

        result = await exec_task
        # Sync project.db current_stage with engine_state
        try:
            db = ProjectDB(name)
            engine_state = EngineState(project_dir)
            db.set_stage(engine_state.current_stage)
            db.close()
        except Exception:
            pass
        yield {"data": json.dumps({"status": "done", "stage": "review", "result": str(result)[:500]}, ensure_ascii=False)}
    except Exception as e:
        yield {"data": json.dumps({"status": "error", "message": str(e)}, ensure_ascii=False)}
