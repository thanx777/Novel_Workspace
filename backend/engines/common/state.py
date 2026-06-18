"""引擎状态管理 — 单一真理来源，替代 outline_state.json + project.db.current_stage。"""

import json
import os
from typing import Any, Dict, List, Optional


class EngineState:
    """管理引擎的全局状态，持久化到 <project_dir>/engine_state.json。"""

    def __init__(self, project_dir: str):
        self.project_dir = project_dir
        self.path = os.path.join(project_dir, "engine_state.json")
        self._data: Dict[str, Any] = self._load()

    # ---- 持久化 ----

    def _load(self) -> Dict:
        if os.path.isfile(self.path):
            try:
                with open(self.path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                print(f"[warn] 引擎状态文件加载失败，回退到默认值: {self.path} - {e}")
        return self._default()

    @staticmethod
    def _default() -> Dict:
        return {
            "current_stage": "outline",  # outline | writing | review | completed
            "outline": {"status": "pending", "current_layer": None, "rounds": [], "completed_layers": []},
            "writing": {"status": "pending", "current_chapter": 0, "total_chapters": 0, "rounds": [], "completed_chapters": []},
            "review": {"status": "pending", "dimensions_done": [], "rounds": []},
        }

    def save(self):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self._data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, self.path)

    # ---- 读写 ----

    @property
    def data(self) -> Dict:
        return self._data

    def get(self, key: str, default=None):
        return self._data.get(key, default)

    def set(self, key: str, value: Any):
        self._data[key] = value
        self.save()

    # ---- 阶段管理 ----

    @property
    def current_stage(self) -> str:
        return self._data.get("current_stage", "outline")

    @current_stage.setter
    def current_stage(self, stage: str):
        assert stage in ("outline", "outline_review", "writing", "review", "completed")
        self._data["current_stage"] = stage
        self.save()

    # ---- 大纲状态 ----

    def outline_add_round(self, round_num: int, layer: str, score: float, issues: List[str]):
        stage = self._data.setdefault("outline", {})
        rounds = stage.setdefault("rounds", [])
        rounds.append({"round": round_num, "layer": layer, "score": score, "issues": issues})
        stage["current_layer"] = layer
        self.save()

    def outline_complete_layer(self, layer: str):
        stage = self._data.setdefault("outline", {})
        completed = stage.setdefault("completed_layers", [])
        if layer not in completed:
            completed.append(layer)
        self.save()

    def outline_set_status(self, status: str):
        self._data.setdefault("outline", {})["status"] = status
        self.save()

    # ---- 写作状态 ----

    def writing_add_round(self, round_num: int, chapter: int, action: str, score: float, issues: List[str]):
        stage = self._data.setdefault("writing", {})
        rounds = stage.setdefault("rounds", [])
        rounds.append({"round": round_num, "chapter": chapter, "action": action, "score": score, "issues": issues})
        # 只保留最近200轮记录，避免无限增长
        if len(rounds) > 200:
            stage["rounds"] = rounds[-200:]
        stage["current_chapter"] = chapter
        self.save()

    def writing_complete_chapter(self, chapter: int):
        stage = self._data.setdefault("writing", {})
        completed = stage.setdefault("completed_chapters", [])
        if chapter not in completed:
            completed.append(chapter)
        self.save()

    def writing_set_status(self, status: str):
        self._data.setdefault("writing", {})["status"] = status
        self.save()

    # ---- 审校状态 ----

    def review_add_round(self, round_num: int, dimension: str, score: float, issues: List[str]):
        stage = self._data.setdefault("review", {})
        rounds = stage.setdefault("rounds", [])
        rounds.append({"round": round_num, "dimension": dimension, "score": score, "issues": issues})
        self.save()

    def review_set_status(self, status: str):
        self._data.setdefault("review", {})["status"] = status
        self.save()
