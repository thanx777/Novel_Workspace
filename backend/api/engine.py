import os

from fastapi import APIRouter, Depends

from project_db import get_project_dir
from engines.common.state import EngineState
from .engine_registry import _running_engines
from .logs import _read_run_log
from .auth import require_auth

router = APIRouter()


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
        # 清空文件内容而非删除，避免 Windows 文件锁导致 PermissionError
        try:
            with open(log_path, "w", encoding="utf-8") as f:
                f.truncate(0)
        except PermissionError:
            pass
    return {"success": True}


@router.post("/projects/{name}/engine/stop")
async def engine_stop(name: str, user=Depends(require_auth)):
    """停止当前运行的引擎。设置取消标志并立即保存 paused 状态。"""
    engine = _running_engines.get(name)
    if engine is not None:
        engine.cancelled = True
        # 立即保存状态，确保断点续传能正确恢复
        if hasattr(engine, 'state'):
            # 审校引擎：保存 paused 状态
            if hasattr(engine.state, 'review_set_status'):
                engine.state.review_set_status("paused")
            # 写作引擎：保存 writing 状态为 paused
            elif hasattr(engine.state, 'writing_set_status'):
                engine.state.writing_set_status("paused")
            # 大纲引擎：保存 outline 状态为 paused
            elif hasattr(engine.state, 'outline_set_status'):
                engine.state.outline_set_status("paused")
        return {"success": True, "message": "引擎停止信号已发送"}
    return {"success": True, "message": "没有正在运行的引擎"}
