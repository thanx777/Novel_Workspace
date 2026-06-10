"""BaseEngine — 三引擎共享的 MWR 循环骨架。"""

import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .llm_client import LLMClient
from .kg_adapter import KGAdapter
from .state import EngineState
from .genre_adapter import GenreAdapter
from .hallucination_guard import HallucinationGuardAdapter


@dataclass
class MWRTask:
    """Manager 分配给 Writer/Reviewer 的任务。"""
    action: str                    # "write" | "polish" | "review"
    layer: str = ""                # L1/L2/L3（大纲引擎用）
    chapter_num: int = 0           # 章节号（写作引擎用）
    dimension: str = ""            # 审校维度（审校引擎用）
    focus_issues: List[str] = field(default_factory=list)  # 上一轮 Reviewer 反馈
    context: str = ""              # 额外上下文


@dataclass
class Draft:
    """Writer 产出的草稿。"""
    content: str = ""              # markdown 正文
    json_data: Dict = field(default_factory=dict)  # 结构化数据
    layer: str = ""                # L1/L2/L3
    chapter_num: int = 0           # 章节号
    metadata: Dict = field(default_factory=dict)


@dataclass
class ReviewResult:
    """Reviewer 评审结果。"""
    score: float = 0.0            # 0-10
    issues: List[str] = field(default_factory=list)
    suggestions: List[str] = field(default_factory=list)
    all_required_passed: bool = False  # 硬性校验是否全过
    hallucination_warnings: List[str] = field(default_factory=list)  # 幻觉警告
    raw_response: str = ""


@dataclass
class FinalDecision:
    """Manager 最终决策。"""
    accepted: bool = True
    reason: str = ""


class BaseEngine(ABC):
    """三引擎共享的 MWR 循环骨架。

    子类只需实现 4 个方法：
    - manager_decide(round_num) -> MWRTask
    - writer_execute(task) -> Draft
    - reviewer_evaluate(draft) -> ReviewResult
    - manager_final_decision() -> FinalDecision
    """

    def __init__(self, project_dir: str, project_name: str,
                 project_presets: Optional[Dict[str, Dict]] = None,
                 global_presets: Optional[List[Dict]] = None,
                 kg=None,
                 yield_func=None,
                 genre: str = ""):
        self.project_dir = project_dir
        self.project_name = project_name
        self.llm = LLMClient(project_presets=project_presets,
                             global_presets=global_presets)
        self.kg_adapter = KGAdapter(kg=kg, project_dir=project_dir)
        self.state = EngineState(project_dir)
        self.genre_adapter = GenreAdapter(genre_name=genre)
        self.hallucination_guard = HallucinationGuardAdapter()
        self.yield_func = yield_func or (lambda x: None)
        self.cancelled = False  # 外部可设置，用于中断 MWR 循环

    def _emit(self, data: Dict):
        """发送状态更新。"""
        if self.yield_func:
            self.yield_func(data)

    async def run_mwr_cycle(self, max_rounds: int = 5,
                            score_threshold: float = 8.0) -> ReviewResult:
        """通用 MWR 循环。

        1. Manager 决定本轮任务
        2. Writer 执行
        3. Reviewer 评审
        4. 如果 score >= threshold 且硬性校验全过 → 停止
        5. 否则 Manager 把 Reviewer 反馈传给 Writer 重做
        """
        last_result = None
        consecutive_same_failures = 0
        prev_issues_key = None

        for round_num in range(1, max_rounds + 1):
            # 检查是否已被用户取消
            if self.cancelled:
                self._emit({"status": "cycle_cancelled", "round": round_num, "reason": "用户取消"})
                return last_result or ReviewResult(score=0.0, issues=["用户取消"])

            self._emit({"status": "mwr_round", "round": round_num, "max_rounds": max_rounds})

            # 1. Manager 决定任务
            task = self.manager_decide(round_num, last_result)
            self._emit({"status": "manager_decided", "round": round_num, "action": task.action})

            # 2. Writer 执行
            draft = await self.writer_execute(task)
            self._emit({"status": "writer_done", "round": round_num})

            # 3. Reviewer 评审
            result = await self.reviewer_evaluate(draft)
            last_result = result
            self._emit({
                "status": "reviewer_done", "round": round_num,
                "score": result.score, "issues": result.issues,
                "all_required_passed": result.all_required_passed,
            })

            # 4. 判断是否通过
            if result.score >= score_threshold and result.all_required_passed:
                self._on_cycle_completed(round_num, result)
                self._emit({"status": "cycle_completed", "round": round_num, "score": result.score})
                return result

            # 5. 连续相同问题检测：如果连续 3 轮评分低于阈值且问题相同，提前退出
            if result.score < score_threshold:
                issues_key = tuple(sorted(result.issues))
                if issues_key == prev_issues_key:
                    consecutive_same_failures += 1
                else:
                    consecutive_same_failures = 1
                    prev_issues_key = issues_key
                if consecutive_same_failures >= 3:
                    self._emit({"status": "cycle_stuck", "round": round_num,
                                "reason": f"连续{consecutive_same_failures}轮相同问题未解决，提前退出"})
                    self._emit({"status": "cycle_ended", "accepted": False,
                                "reason": f"连续{consecutive_same_failures}轮相同问题未解决"})
                    return result
            else:
                consecutive_same_failures = 0
                prev_issues_key = None

        # 6. 达到上限，Manager 做最终决策
        final = self.manager_final_decision()
        if final.accepted:
            self._on_cycle_completed(max_rounds, last_result)
        self._emit({"status": "cycle_ended", "accepted": final.accepted, "reason": final.reason})
        return last_result or ReviewResult(score=0.0, issues=["达到最大轮数且无评审结果"])

    @abstractmethod
    def manager_decide(self, round_num: int, last_result: Optional[ReviewResult] = None) -> MWRTask:
        """Manager 决定本轮任务。"""
        ...

    @abstractmethod
    async def writer_execute(self, task: MWRTask) -> Draft:
        """Writer 执行写作任务。"""
        ...

    @abstractmethod
    async def reviewer_evaluate(self, draft: Draft) -> ReviewResult:
        """Reviewer 评审草稿。"""
        ...

    @abstractmethod
    def manager_final_decision(self) -> FinalDecision:
        """Manager 最终决策（达到轮数上限时）。"""
        ...

    def _on_cycle_completed(self, round_num: int, result: ReviewResult):
        """循环完成后的钩子（子类可覆盖）。"""
        pass
