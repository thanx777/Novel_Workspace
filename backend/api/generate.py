import asyncio
import json

from fastapi import APIRouter
from sse_starlette.sse import EventSourceResponse

from project_db import ProjectDB, get_project_dir
from knowledge_graph import KnowledgeGraph
from engines.common.state import EngineState
from engines.outline.engine import OutlineEngine
from engines.writing.engine import WritingEngine
from engines.review.engine import ReviewEngine
from .schemas import OutlineGenerateRequest, WritingStartRequest
from .engine_registry import (
    _running_engines, _engine_lock,
    _get_project_presets, _get_project_genre, _get_global_presets,
)
from .logs import _append_run_log

router = APIRouter()


# ---- SSE 流式引擎端点（日志实时推送） ----

@router.post("/projects/{name}/outline/generate/stream")
async def outline_generate_stream(name: str, req: OutlineGenerateRequest):
    """大纲 MWR 循环生成（SSE 流式，实时推送进度日志）。"""
    return EventSourceResponse(_outline_generate_stream(name, req))


async def _run_engine_stream(
    name: str,
    stage: str,
    setup,
    make_done_event=None,
):
    """通用 SSE 引擎流：封装并发保护、消息队列、主循环、清理逻辑。

    Args:
        name: 项目名
        stage: 阶段名（outline / writing / review）
        setup: 回调函数 (name, project_dir, q_emit) -> (engine, exec_task, start_events: list[dict])
        make_done_event: 可选回调 (result) -> dict，默认返回标准 done 事件
    """
    # 并发保护：加锁防止竞态
    async with _engine_lock:
        existing = _running_engines.get(name)
        if existing is not None:
            existing.cancelled = True
            _running_engines.pop(name, None)
            await asyncio.sleep(0.3)

    project_dir = get_project_dir(name)
    q = asyncio.Queue()

    def q_emit(data):
        try:
            q.put_nowait(data)
        except Exception:
            pass

    # 引擎创建 + 任务启动 + 起始事件
    engine, exec_task, start_events = setup(name, project_dir, q_emit)
    _running_engines[name] = engine
    for evt in start_events:
        q_emit(evt)

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

        if make_done_event:
            done_event = make_done_event(result)
        else:
            done_event = {"status": "done", "stage": stage, "result": str(result)[:500]}
        _append_run_log(project_dir, done_event)
        yield {"data": json.dumps(done_event, ensure_ascii=False)}
    except Exception as e:
        err_event = {"status": "error", "message": str(e)}
        _append_run_log(project_dir, err_event)
        yield {"data": json.dumps(err_event, ensure_ascii=False)}
    finally:
        _running_engines.pop(name, None)
        if not exec_task.done():
            engine.cancelled = True
            exec_task.cancel()


async def _outline_generate_stream(name: str, req: OutlineGenerateRequest):
    def setup(name, project_dir, q_emit):
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
            yield_func=q_emit,
        )

        # 从 engine_state.json 恢复大纲进度：跳过已完成的层
        resume_info = ""
        if not req.layer:
            engine_state = EngineState(project_dir)
            completed = engine_state.data.get("outline", {}).get("completed_layers", [])
            if completed:
                resume_info = f"（已完成: {', '.join(completed)}，从下一层继续）"

        exec_task = asyncio.create_task(
            engine.generate_all(requirements=req.requirements) if not req.layer
            else engine.generate_layer(req.layer, requirements=req.requirements)
        )
        start_events = [{"status": "start", "stage": "outline", "message": f"🚀 开始大纲生成{resume_info}"}]
        return engine, exec_task, start_events

    async for chunk in _run_engine_stream(name, "outline", setup):
        yield chunk


@router.post("/projects/{name}/writing/start/stream")
async def writing_start_stream(name: str, req: WritingStartRequest):
    """写作引擎（SSE 流式，实时推送进度日志）。"""
    return EventSourceResponse(_writing_start_stream(name, req))


async def _writing_start_stream(name: str, req: WritingStartRequest):
    def setup(name, project_dir, q_emit):
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
            yield_func=q_emit,
        )

        # 从 engine_state.json 恢复进度：如果已有完成章节，从下一章继续
        start_chapter = req.start_chapter
        start_events = []
        if start_chapter <= 1:
            engine_state = EngineState(project_dir)
            completed = engine_state.data.get("writing", {}).get("completed_chapters", [])
            if completed:
                start_chapter = max(completed) + 1
                start_events.append({"status": "info", "stage": "writing", "message": f"📋 从第 {start_chapter} 章继续（已完成 {len(completed)} 章）"})

        exec_task = asyncio.create_task(engine.write_all(start_chapter=start_chapter))
        start_events.append({"status": "start", "stage": "writing", "message": "🚀 开始写作"})
        return engine, exec_task, start_events

    async for chunk in _run_engine_stream(name, "writing", setup):
        yield chunk


@router.post("/projects/{name}/review/start/stream")
async def review_start_stream(name: str):
    """全局审校引擎（SSE 流式，实时推送进度日志）。"""
    return EventSourceResponse(_review_start_stream(name))


async def _review_start_stream(name: str):
    def setup(name, project_dir, q_emit):
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
            yield_func=q_emit,
        )

        exec_task = asyncio.create_task(engine.run_review())
        start_events = [{"status": "start", "stage": "review", "message": "🚀 开始全局审校"}]
        return engine, exec_task, start_events

    def make_done_event(result):
        is_cancelled = isinstance(result, dict) and result.get("cancelled")
        if is_cancelled:
            return {"status": "review_cancelled", "stage": "review", "message": "审校已暂停，可继续"}
        return {"status": "done", "stage": "review", "result": str(result)[:500]}

    async for chunk in _run_engine_stream(name, "review", setup, make_done_event):
        yield chunk
