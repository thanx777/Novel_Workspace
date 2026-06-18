import os
import json
from typing import List


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
