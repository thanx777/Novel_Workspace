"""BaseEngine — 三引擎共享的 MWR 循环骨架。"""

import os
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .llm_client import LLMClient
from .kg_adapter import KGAdapter
from .state import EngineState
from .genre_adapter import GenreAdapter
from .hallucination_guard import HallucinationGuardAdapter
from .prompts import get_formatted_prompts, ENGINE_CONFIG


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
        self.yield_func = yield_func or (lambda x: None)
        self.cancelled = False  # 外部可设置，用于中断 MWR 循环

        # 引擎配置与提示词（深拷贝避免污染全局 ENGINE_CONFIG）
        self.mode_config = dict(ENGINE_CONFIG)
        self.prompts = get_formatted_prompts()

        # 从项目DB读取项目级配置，覆盖全局默认值
        try:
            from project_db import ProjectDB
            db = ProjectDB(project_name)
            proj = db.get_project()
            if proj:
                for key in ("word_count_min", "word_count_max", "max_rounds_writing", "max_rounds_outline", "max_polish_rounds"):
                    val = proj.get(key)
                    if val is not None:
                        self.mode_config[key] = int(val)
        except Exception as e:
            self._emit({"status": "warning", "message": f"读取项目配置失败，使用默认值: {e}"})

        # 使用项目级字数配置创建 HallucinationGuardAdapter（实例级，不污染类属性）
        self.hallucination_guard = HallucinationGuardAdapter(
            word_count_min=self.mode_config["word_count_min"],
            word_count_max=self.mode_config["word_count_max"],
        )

    def _emit(self, data: Dict):
        """发送状态更新。"""
        if self.yield_func:
            self.yield_func(data)

    # ---- 公共文件操作（子类共享，避免重复代码）----

    def _chapter_path(self, chapter_num: int) -> str:
        """获取章节文件路径，确保目录存在。"""
        d = os.path.join(self.project_dir, "chapters")
        os.makedirs(d, exist_ok=True)
        return os.path.join(d, f"第{chapter_num}章.txt")

    def _write_atomic(self, path: str, content: str):
        """原子写入文件：先写 .tmp，再 os.replace 替换。"""
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(content)
        os.replace(tmp, path)

    def _read_chapter(self, chapter_num: int) -> str:
        """读取指定章节全文，不存在则返回空字符串。"""
        path = self._chapter_path(chapter_num)
        if os.path.isfile(path):
            with open(path, "r", encoding="utf-8") as f:
                return f.read()
        return ""

    def _clean_fs_ids(self, content: str) -> str:
        """清洗 LLM 输出中的 FS 编号（如 FS-001、FS-002-Variant 等）。"""
        content = re.sub(r"\bFS-\d+(?:-\d+)?(?:-Variant)?\b", "", content)
        content = re.sub(r"[（(]\s*[）)]", "", content)
        return content

    def _read_recent_chapters(self, n: int = 3) -> str:
        """读取最近章节上下文：前2章给结尾摘要，紧邻章给全文以保证完美衔接。"""
        parts = []
        start = max(1, self._current_chapter - n)
        for ch in range(start, self._current_chapter):
            is_adjacent = (ch == self._current_chapter - 1)
            content = self._read_chapter(ch)
            if content:
                content = self._clean_fs_ids(content)
                if is_adjacent:
                    # 紧邻章：注入全文，保证完美衔接
                    parts.append(f"【第{ch}章·全文 — 必须自然衔接】\n{content}")
                else:
                    # 前2章：只注入结尾段落（KG 前情提要在融合记忆中已全局覆盖）
                    tail_len = 500
                    if len(content) > tail_len:
                        content = f"[前文摘要]\n{content[-tail_len:]}"
                    parts.append(f"【第{ch}章·结尾】\n{content}")
        return "\n\n".join(parts)

    def _format_feedback_context(self, result: ReviewResult) -> str:
        """格式化 Reviewer 反馈，供下一轮 Writer 使用。"""
        parts = []
        if result.issues:
            parts.append("问题：\n" + "\n".join(f"- {i}" for i in result.issues))
        if result.suggestions:
            parts.append("建议：\n" + "\n".join(f"- {s}" for s in result.suggestions))
        if result.hallucination_warnings:
            parts.append("幻觉警告：\n" + "\n".join(f"- {w}" for w in result.hallucination_warnings))
        return "\n\n".join(parts)

    async def run_mwr_cycle(self, max_rounds: int = 5,
                            score_threshold: float = 8.0) -> ReviewResult:
        """通用 MWR 循环。

        1. Manager 决定本轮任务
        2. Writer 执行
        3. Reviewer 评审
        4. 如果 score >= threshold 且硬性校验全过 → 停止
        5. 否则 Manager 把 Reviewer 反馈传给 Writer 修改
        6. 连续 N 轮评分无提升 → 卡住，停止
        """
        last_result = None
        self._issue_consecutive_counts = {}
        best_score = 0.0
        recent_scores = []  # 滑动窗口：记录未超过best_score的轮次
        NO_IMPROVE_WINDOW = 3  # 最近3轮无提升则认为卡住
        consecutive_llm_errors = 0  # 连续LLM错误计数

        round_num = 0
        while True:
            round_num += 1

            # 润色轮次硬上限（使用传入的 max_rounds 参数）
            if round_num > max_rounds:
                self._emit({"status": "cycle_max_rounds", "round": round_num, "reason": f"达到润色轮次上限({max_rounds})"})
                break

            # 检查是否已被用户取消
            if self.cancelled:
                self._emit({"status": "cycle_cancelled", "round": round_num, "reason": "用户取消"})
                return last_result or ReviewResult(score=0.0, issues=["用户取消"])

            self._emit({"status": "mwr_round", "round": round_num, "max_rounds": max_rounds})

            # 1. Manager 决定任务
            task = self.manager_decide(round_num, last_result)
            self._emit({"status": "manager_decided", "round": round_num, "action": task.action})

            # accept_current：润色用尽，走 final_decision 钩子后结束循环
            if task.action == "accept_current":
                self._emit({"status": "cycle_ended", "accepted": True, "reason": "润色次数用尽，接受当前内容"})
                final = self.manager_final_decision()
                if final.accepted:
                    self._on_cycle_completed(round_num, last_result)
                return last_result or ReviewResult(score=0.0, issues=["润色用尽"])

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

            # 3.5 连续LLM错误检测：连续3轮score=0且all_required_passed=false，停止循环
            if result.score == 0.0 and not result.all_required_passed:
                consecutive_llm_errors += 1
                if consecutive_llm_errors >= 3:
                    self._emit({"status": "cycle_stuck", "round": round_num,
                                "reason": f"连续{consecutive_llm_errors}轮LLM错误/空内容，停止循环"})
                    break
            else:
                consecutive_llm_errors = 0

            # 4. 判断是否通过
            if result.score >= score_threshold and result.all_required_passed:
                self._on_cycle_completed(round_num, result)
                self._emit({"status": "cycle_completed", "round": round_num, "score": result.score})
                return result

            # 5. 卡住检测（滑动窗口）：最近N轮评分均未超过best_score则停止
            if result.score > best_score:
                best_score = result.score
                recent_scores = []  # 有提升，重置窗口
            else:
                recent_scores.append(result.score)

            if len(recent_scores) >= NO_IMPROVE_WINDOW:
                self._emit({"status": "cycle_stuck", "round": round_num,
                            "reason": f"连续{NO_IMPROVE_WINDOW}轮评分无提升（最高{best_score:.1f}），停止循环"})
                break

            # 6. 收益递减检测：评分接近阈值且连续2轮变化<0.3，提前退出
            if len(recent_scores) >= 2 and best_score >= (score_threshold - 0.5):
                last_two = recent_scores[-2:]
                if abs(last_two[0] - last_two[1]) < 0.3:
                    self._emit({"status": "cycle_diminishing", "round": round_num,
                                "reason": f"评分接近阈值({best_score:.1f})且收益递减，提前结束"})
                    break

            # 6. 连续相同问题检测：发出警告但继续
            if result.score < score_threshold or not result.all_required_passed:
                current_issues_set = set(result.issues)
                new_issue_counts = {}
                for issue in current_issues_set:
                    new_issue_counts[issue] = self._issue_consecutive_counts.get(issue, 0) + 1
                self._issue_consecutive_counts = new_issue_counts
                stuck_issues = [iss for iss, cnt in self._issue_consecutive_counts.items() if cnt >= 3]
                if stuck_issues:
                    self._emit({"status": "cycle_stuck", "round": round_num,
                                "reason": f"连续3轮未解决问题: {stuck_issues[:3]}，提前退出"})
                    self._issue_consecutive_counts = {}
                    break
            else:
                self._issue_consecutive_counts = {}

        # 循环结束
        final = self.manager_final_decision()
        if final.accepted:
            self._on_cycle_completed(round_num, last_result)
        self._emit({"status": "cycle_ended", "accepted": final.accepted, "reason": final.reason})
        return last_result or ReviewResult(score=0.0, issues=["循环结束且无评审结果"])

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
