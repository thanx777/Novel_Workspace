import os
import json
import asyncio
from typing import List, Dict

from project_db import ProjectDB

# 当前运行的引擎引用（用于 stop 端点取消），按项目名索引
_running_engines: Dict[str, object] = {}
# 引擎启动/停止的互斥锁，防止并发竞态
_engine_lock = asyncio.Lock()


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
        config_path = os.path.join(os.path.dirname(__file__), "..", "config.json")
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
