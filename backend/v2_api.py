"""
v2 API 模块：分层大纲 + 知识图谱的 API 端点
设计为 FastAPI router，可被 main.py 直接 include。
"""
import os
import json
import time
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
from knowledge_graph import KnowledgeGraph, NODE_COLORS, LAYER_COLORS
from engines.common.kg_adapter import KGAdapter
from engines.common.llm_client import LLMClient
from engines.common.genre_adapter import GenreAdapter
from engines.common.hallucination_guard import HallucinationGuardAdapter
from memory_pipeline import IngestPipeline
from engines.common.state import EngineState

router = APIRouter(prefix="/api/v2", tags=["v2"])

# 当前运行的引擎引用（用于 stop 端点取消）
_running_engine = None


# ============================================================
# 日志持久化
# ============================================================

def _append_run_log(project_dir: str, event: dict):
    """将一条 SSE 事件追加到项目的 run_log.jsonl。"""
    log_path = os.path.join(project_dir, "run_log.jsonl")
    try:
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")
    except Exception:
        pass


def _read_run_log(project_dir: str, limit: int = 100) -> List[dict]:
    """读取项目的历史日志（最新的 limit 条）。"""
    log_path = os.path.join(project_dir, "run_log.jsonl")
    if not os.path.isfile(log_path):
        return []
    try:
        with open(log_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
        # 返回最新的 limit 条
        return [json.loads(line) for line in lines[-limit:] if line.strip()]
    except Exception:
        return []


# ============================================================
# 数据模型
# ============================================================

class ProjectCreateRequest(BaseModel):
    name: str
    title: str = ""
    genre: str = ""
    total_chapters: int = 0
    description: str = ""
    outline_layers: Optional[Dict[str, bool]] = None  # {"L1": true, "L2": true}
    extra_requirements: str = ""
    role_presets: Optional[Dict[str, Dict]] = None  # {"manager": {...}, "worker": {...}, ...}


class OutlineLayersRequest(BaseModel):
    layers: Dict[str, bool]


class OutlineNodeEditRequest(BaseModel):
    label: Optional[str] = None
    summary: Optional[str] = None
    attrs: Optional[Dict[str, Any]] = None


class AiEditRequest(BaseModel):
    instruction: str


def _extract_chapter_title(content: str) -> str:
    """从章节内容中提取标题。"""
    import re as _re
    for line in content.strip().split("\n"):
        line = line.strip()
        if not line:
            continue
        if line.startswith("---PREV:") or line.startswith("---CAST:") or line.startswith("---"):
            continue
        m = _re.match(r"^#+\s*第[一二三四五六七八九十百千\d]+章\s*(.*)", line)
        if m and m.group(1).strip():
            return m.group(1).strip()
        m = _re.match(r"^第[一二三四五六七八九十百千\d]+章\s+(.*)", line)
        if m and m.group(1).strip():
            return m.group(1).strip()
        m = _re.match(r"^#+\s*(.+)", line)
        if m and m.group(1).strip():
            title = m.group(1).strip()
            title = _re.sub(r"^第[一二三四五六七八九十百千\d]+章\s*", "", title)
            return title.strip() or "第N章"
        continue
    return "第N章"


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
        # 合并进度数据，让前端能获取 chapters_done 和 total_words
        progress = db.get_progress()
        info["chapters_done"] = progress.get("done", 0)
        info["total_words"] = progress.get("total_words", 0)
        return info
    except Exception as e:
        raise HTTPException(404, f"Project not found: {e}")


@router.post("/projects/{name}/sync-chapters")
def sync_chapters(name: str):
    """手动触发：从已有章节文件中同步章节标题到数据库。
    只同步已有实际内容的章节，不创建空章节条目。
    """
    import re as _re
    project_dir = get_project_dir(name)
    db = ProjectDB(name)
    chapters_found = {}

    # 1. 从已写好的章节文件中提取标题
    chapters_dir = os.path.join(project_dir, "chapters")
    if os.path.isdir(chapters_dir):
        for fname in os.listdir(chapters_dir):
            m = _re.match(r"第(\d+)章\.txt$", fname)
            if not m:
                continue
            idx = int(m.group(1))
            fpath = os.path.join(chapters_dir, fname)
            try:
                with open(fpath, "r", encoding="utf-8") as f:
                    content = f.read()
                if not content.strip():
                    continue  # 跳过空文件
                # 优先从章节内容中提取标题（内容是最新的）
                title = _extract_chapter_title(content)
                if not title or title == "第N章":
                    # 兜底：从 chapter_titles.json 获取标题
                    titles_path = os.path.join(project_dir, "chapter_titles.json")
                    if os.path.isfile(titles_path):
                        try:
                            with open(titles_path, "r", encoding="utf-8") as tf:
                                titles_map = json.load(tf)
                            title = titles_map.get(str(idx), f"第{idx}章")
                        except Exception:
                            title = f"第{idx}章"
                else:
                    title = f"第{idx}章 " + title
                chapters_found[idx] = title
            except Exception:
                chapters_found[idx] = f"第{idx}章"

    # 2. 写入数据库（只写入有内容的章节，补充 word_count 和 status）
    for idx, title in chapters_found.items():
        fpath = os.path.join(project_dir, "chapters", f"第{idx}章.txt")
        content = read_file_safe(fpath, "")
        word_count = len(content.replace(" ", "").replace("\n", "")) if content else 0
        status = "drafted" if content.strip() else "not_started"
        db.upsert_chapter(idx, title=title, word_count=word_count, status=status)

    # 3. 更新 total_chapters（优先从 L1 JSON，其次从 chapter_titles.json，最后数 L2 章节）
    total = 0
    # 3a. 优先从 L1 JSON 的 basic.总章节数 提取（支持范围格式如"120-150"取最大值）
    try:
        l1_json_path = os.path.join(project_dir, "outline_L1.json")
        if os.path.isfile(l1_json_path):
            with open(l1_json_path, "r", encoding="utf-8") as f:
                l1_json = json.load(f)
            tc = l1_json.get("basic", {}).get("总章节数", "")
            if tc:
                tc_str = str(tc).strip()
                range_m = _re.match(r"(\d+)\s*[-–—]\s*(\d+)", tc_str)
                if range_m:
                    total = int(range_m.group(2))
                elif tc_str.isdigit():
                    total = int(tc_str)
    except Exception:
        pass
    # 3b. 从 chapter_titles.json 获取
    if total == 0:
        titles_path = os.path.join(project_dir, "chapter_titles.json")
        if os.path.isfile(titles_path):
            try:
                with open(titles_path, "r", encoding="utf-8") as f:
                    titles_map = json.load(f)
                total = len(titles_map)
            except Exception:
                pass
    # 3c. 数 L2 中的章节标题
    if total == 0:
        l2_path = os.path.join(project_dir, "outline_L2.md")
        if os.path.isfile(l2_path):
            with open(l2_path, "r", encoding="utf-8") as f:
                l2_md = f.read()
            for m in _re.finditer(r"###\s*第\s*(\d+)\s*章", l2_md):
                total += 1
    # 3d. 从 L2 阶段范围推断
    if total == 0:
        l2_path = os.path.join(project_dir, "outline_L2.md")
        if os.path.isfile(l2_path):
            with open(l2_path, "r", encoding="utf-8") as f:
                l2_md = f.read()
            max_ch = 0
            for m in _re.finditer(r"第\s*(\d+)\s*[-–—]\s*(\d+)\s*章", l2_md):
                end_ch = int(m.group(2))
                if end_ch > max_ch:
                    max_ch = end_ch
            if max_ch > 0:
                total = max_ch
    if total > 0:
        db.update_project(total_chapters=total)

    db.close()
    return {"synced": len(chapters_found), "total_chapters": total}


@router.post("/projects/{name}/chapters/{chapter_num}/ai-edit")
async def ai_edit_chapter(name: str, chapter_num: int, req: AiEditRequest):
    """AI修改章节：根据用户指令对已有章节进行修改。"""
    import re as _re

    # a. 获取项目目录
    project_dir = get_project_dir(name)

    # b. 读取章节全文
    chapter_path = os.path.join(project_dir, "chapters", f"第{chapter_num}章.txt")
    if not os.path.isfile(chapter_path):
        raise HTTPException(404, f"章节文件不存在：{chapter_path}")
    chapter_content = read_file_safe(chapter_path, "")
    if not chapter_content.strip():
        raise HTTPException(404, f"章节内容为空：第{chapter_num}章")

    # c. 加载KG
    kg = KnowledgeGraph(project_dir)
    kg.load()

    # d. 创建KGAdapter
    kg_adapter = KGAdapter(kg)

    # e. 获取KG上下文
    character_ctx = kg_adapter.format_character_context()
    foreshadowing_ctx = kg_adapter.format_foreshadowing_context()

    # f. 获取体裁规范
    genre = _get_project_genre(name)
    genre_adapter = GenreAdapter(genre_name=genre)
    genre_injection = genre_adapter.get_writer_injection()

    # g. 获取反幻觉上下文
    hallucination_adapter = HallucinationGuardAdapter()
    hallucination_ctx = hallucination_adapter.get_writing_context(chapter_num)

    # h. 读取前后章摘要
    prev_summary = ""
    next_summary = ""
    prev_path = os.path.join(project_dir, "chapters", f"第{chapter_num - 1}章.txt")
    if os.path.isfile(prev_path):
        prev_text = read_file_safe(prev_path, "")
        prev_summary = prev_text[:300] if prev_text else ""
    next_path = os.path.join(project_dir, "chapters", f"第{chapter_num + 1}章.txt")
    if os.path.isfile(next_path):
        next_text = read_file_safe(next_path, "")
        next_summary = next_text[:300] if next_text else ""

    # i. 构建system_prompt
    system_parts = [
        "你是一位资深小说编辑，擅长根据用户要求修改章节内容。你的任务是：严格按照用户的修改要求，对当前章节进行修改，同时保持与前后章节的连贯性和一致性。",
        "修改原则：\n"
        "1. 只修改用户要求的部分，尽量保留原文中不冲突的内容\n"
        "2. 保持人物性格、说话风格一致\n"
        "3. 保持情节逻辑连贯，不引入矛盾\n"
        "4. 保持文风统一，避免AI痕迹\n"
        "5. 返回修改后的完整章节全文，不要省略任何部分",
    ]
    if character_ctx:
        system_parts.append(character_ctx)
    if foreshadowing_ctx:
        system_parts.append(foreshadowing_ctx)
    if genre_injection:
        system_parts.append(genre_injection)
    if hallucination_ctx:
        system_parts.append(hallucination_ctx)
    system_prompt = "\n\n".join(system_parts)

    # j. 构建user_prompt
    user_parts = [f"【当前章节 — 第{chapter_num}章全文】\n{chapter_content}"]
    if prev_summary:
        user_parts.append(f"【前一章（第{chapter_num - 1}章）开头摘要】\n{prev_summary}")
    if next_summary:
        user_parts.append(f"【后一章（第{chapter_num + 1}章）开头摘要】\n{next_summary}")
    user_parts.append(f"【用户修改要求】\n{req.instruction}")
    user_prompt = "\n\n".join(user_parts)

    # k. 调用LLM
    project_presets = _get_project_presets(name)
    global_presets = _get_global_presets()
    llm = LLMClient(project_presets, global_presets)
    result = await llm.call("chat", system_prompt, user_prompt)

    # l. 内容变空检测
    if not result or not result.strip() or result.startswith("[LLM_ERROR"):
        return {"error": "AI修改失败，返回内容为空"}

    # 中文字数缩水检测
    original_count = len(_re.findall(r'[\u4e00-\u9fff]', chapter_content))
    result_count = len(_re.findall(r'[\u4e00-\u9fff]', result))
    if original_count > 0 and result_count < original_count * 0.5:
        return {"error": "AI修改后字数大幅缩水，请重试"}

    # m. 同步更新数据库标题
    try:
        title = _extract_chapter_title(result)
        db = ProjectDB(name)
        db.upsert_chapter(chapter_index=chapter_num, title=title, status="draft")
        db.close()
    except Exception:
        pass

    # n. 返回修改后全文
    return {"content": result}


@router.post("/projects")
def create_project(req: ProjectCreateRequest):
    from project_db import create_project as _cp
    try:
        result = _cp(
            name=req.name or f"project_{int(time.time())}",
            title=req.title or req.name,
            genre=req.genre,
            total_chapters=req.total_chapters,
            outline_review_mode="auto",
            outline_layers=req.outline_layers,
        )
    except Exception as e:
        raise HTTPException(400, f"Create failed: {e}")
    db = ProjectDB(req.name)
    if req.outline_layers:
        db.set_outline_layers(req.outline_layers)
    # 保存角色预设
    if req.role_presets:
        db.set_presets(
            manager=req.role_presets.get("manager"),
            worker=req.role_presets.get("worker"),
            reviewer=req.role_presets.get("reviewer"),
            chat=req.role_presets.get("chat"),
        )
    # 保存附加要求到文件
    if req.extra_requirements:
        project_dir = get_project_dir(req.name)
        req_path = os.path.join(project_dir, "extra_requirements.txt")
        with open(req_path, "w", encoding="utf-8") as f:
            f.write(req.extra_requirements)
    # bootstrap knowledge graph
    project_dir = get_project_dir(req.name)
    kg = KnowledgeGraph(project_dir)
    kg.load()
    return {"success": True, "project": db.get_project(), "outline_layers": db.get_outline_layers()}


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
    """获取全局预设列表（从 config.json 读取，与 main.py /api/presets 一致）。"""
    try:
        config_path = os.path.join(os.path.dirname(__file__), "config.json")
        if os.path.isfile(config_path):
            with open(config_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            presets = data.get("presets", [])
            if isinstance(presets, list):
                return presets
            elif isinstance(presets, dict):
                return list(presets.values())
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
    state = EngineState(project_dir)
    return state.data


@router.get("/projects/{name}/logs")
def get_project_logs(name: str, limit: int = 100):
    """获取项目历史运行日志。"""
    project_dir = get_project_dir(name)
    logs = _read_run_log(project_dir, limit=limit)
    return {"logs": logs}


@router.delete("/projects/{name}/logs")
def clear_project_logs(name: str):
    """清除项目历史运行日志。"""
    project_dir = get_project_dir(name)
    log_path = os.path.join(project_dir, "run_log.jsonl")
    if os.path.isfile(log_path):
        os.remove(log_path)
    return {"success": True}


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

    total = req.total_chapters or db.get_project().get("total_chapters", 0)

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

    total = db.get_project().get("total_chapters", 0)
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
    global _running_engine
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

    global _running_engine
    _running_engine = engine

    # 从 engine_state.json 恢复大纲进度：跳过已完成的层
    resume_info = ""
    if not req.layer:
        engine_state = EngineState(project_dir)
        completed = engine_state.data.get("outline", {}).get("completed_layers", [])
        if completed:
            resume_info = f"（已完成: {', '.join(completed)}，从下一层继续）"

    q_emit({"status": "start", "stage": "outline", "message": f"🚀 开始大纲生成{resume_info}"})

    exec_task = asyncio.create_task(
        engine.generate_all(requirements=req.requirements) if not req.layer
        else engine.generate_layer(req.layer, requirements=req.requirements)
    )

    try:
        while True:
            try:
                msg = await asyncio.wait_for(q.get(), timeout=0.5)
                _append_run_log(project_dir, msg)
                yield {"data": json.dumps(msg, ensure_ascii=False)}
            except asyncio.TimeoutError:
                if exec_task.done():
                    while not q.empty():
                        try:
                            msg = q.get_nowait()
                            _append_run_log(project_dir, msg)
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
        done_event = {"status": "done", "stage": "outline", "result": str(result)[:500]}
        _append_run_log(project_dir, done_event)
        yield {"data": json.dumps(done_event, ensure_ascii=False)}
    except Exception as e:
        err_event = {"status": "error", "message": str(e)}
        _append_run_log(project_dir, err_event)
        yield {"data": json.dumps(err_event, ensure_ascii=False)}
    finally:
        if _running_engine is engine:
            _running_engine = None


@router.post("/projects/{name}/writing/start/stream")
async def writing_start_stream(name: str, req: WritingStartRequest):
    """写作引擎（SSE 流式，实时推送进度日志）。"""
    return EventSourceResponse(_writing_start_stream(name, req))


async def _writing_start_stream(name: str, req: WritingStartRequest):
    global _running_engine
    project_dir = get_project_dir(name)
    db = ProjectDB(name)
    project_presets = db.get_presets()
    global_presets = _get_global_presets()
    kg = KnowledgeGraph(project_dir)
    kg.load()

    total = req.total_chapters or db.get_project().get("total_chapters", 0)

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

    global _running_engine
    _running_engine = engine

    # 从 engine_state.json 恢复进度：如果已有完成章节，从下一章继续
    start_chapter = req.start_chapter
    if start_chapter <= 1:
        engine_state = EngineState(project_dir)
        completed = engine_state.data.get("writing", {}).get("completed_chapters", [])
        if completed:
            start_chapter = max(completed) + 1
            q_emit({"status": "info", "stage": "writing", "message": f"📋 从第 {start_chapter} 章继续（已完成 {len(completed)} 章）"})

    q_emit({"status": "start", "stage": "writing", "message": "🚀 开始写作"})

    exec_task = asyncio.create_task(
        engine.write_all(start_chapter=start_chapter)
    )

    try:
        while True:
            try:
                msg = await asyncio.wait_for(q.get(), timeout=0.5)
                _append_run_log(project_dir, msg)
                yield {"data": json.dumps(msg, ensure_ascii=False)}
            except asyncio.TimeoutError:
                if exec_task.done():
                    while not q.empty():
                        try:
                            msg = q.get_nowait()
                            _append_run_log(project_dir, msg)
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
        done_event = {"status": "done", "stage": "writing", "result": str(result)[:500]}
        _append_run_log(project_dir, done_event)
        yield {"data": json.dumps(done_event, ensure_ascii=False)}
    except Exception as e:
        err_event = {"status": "error", "message": str(e)}
        _append_run_log(project_dir, err_event)
        yield {"data": json.dumps(err_event, ensure_ascii=False)}
    finally:
        if _running_engine is engine:
            _running_engine = None


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

    global _running_engine
    _running_engine = engine

    q_emit({"status": "start", "stage": "review", "message": "🚀 开始全局审校"})

    exec_task = asyncio.create_task(engine.run_review())

    try:
        while True:
            try:
                msg = await asyncio.wait_for(q.get(), timeout=0.5)
                _append_run_log(project_dir, msg)
                yield {"data": json.dumps(msg, ensure_ascii=False)}
            except asyncio.TimeoutError:
                if exec_task.done():
                    while not q.empty():
                        try:
                            msg = q.get_nowait()
                            _append_run_log(project_dir, msg)
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

        # 根据是否被取消推送不同事件
        is_cancelled = isinstance(result, dict) and result.get("cancelled")
        if is_cancelled:
            done_event = {"status": "review_cancelled", "stage": "review", "message": "审校已暂停，可继续"}
        else:
            done_event = {"status": "done", "stage": "review", "result": str(result)[:500]}
        _append_run_log(project_dir, done_event)
        yield {"data": json.dumps(done_event, ensure_ascii=False)}
    except Exception as e:
        err_event = {"status": "error", "message": str(e)}
        _append_run_log(project_dir, err_event)
        yield {"data": json.dumps(err_event, ensure_ascii=False)}
    finally:
        if _running_engine is engine:
            _running_engine = None


@router.post("/projects/{name}/engine/stop")
async def engine_stop(name: str):
    """停止当前运行的引擎。设置取消标志并立即保存 paused 状态。"""
    global _running_engine
    if _running_engine is not None:
        _running_engine.cancelled = True
        # 立即保存 paused 状态，确保断点续校能正确恢复
        # （run_review 可能还在 LLM 调用中，来不及保存 paused）
        if hasattr(_running_engine, 'state') and hasattr(_running_engine.state, 'review_set_status'):
            _running_engine.state.review_set_status("paused")
        return {"success": True, "message": "引擎停止信号已发送"}
    return {"success": True, "message": "没有正在运行的引擎"}
