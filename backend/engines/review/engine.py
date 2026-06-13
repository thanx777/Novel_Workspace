"""全局审校引擎 — MWR 循环，按维度审校全书。"""

import os
import re
import json
from typing import Dict, List, Optional

from ..common.base_engine import BaseEngine, MWRTask, Draft, ReviewResult, FinalDecision
from ..common.llm_client import LLMClient
from ..common.kg_adapter import KGAdapter
from ..common.state import EngineState
from ..common.prompts import REVIEWER_SYSTEM_REVIEW  # 保留导入以向后兼容


# 全部审校维度（pro 模式使用完整列表）
_ALL_REVIEW_DIMENSIONS = [
    ("character_arc", "人物弧光", "检查主角/配角从第1章到最后一章的性格变化是否合理"),
    ("foreshadowing", "伏笔回收", "检查所有伏笔是否都有回收章节"),
    ("consistency", "跨章一致性", "检查时间线、角色状态、场景描述是否前后矛盾"),
    ("style", "风格统一", "检查文笔风格、叙事视角是否一致"),
    ("coolpoint_hook", "爽点与钩子", "检查爽点密度和章末钩子是否到位"),
    ("ai_trace", "AI痕迹", "检测重复句式、万能形容词、说道滥用"),
]

# 向后兼容：默认 standard 模式的维度
REVIEW_DIMENSIONS = _ALL_REVIEW_DIMENSIONS[:4]


class ReviewEngine(BaseEngine):
    """全局审校引擎：按维度 MWR 循环审校。"""

    def __init__(self, project_dir: str, project_name: str,
                 project_presets: Optional[Dict[str, Dict]] = None,
                 global_presets: Optional[List[Dict]] = None,
                 kg=None, yield_func=None,
                 max_rounds_per_dimension: Optional[int] = None,
                 score_threshold: Optional[float] = None,
                 genre: str = ""):
        super().__init__(project_dir, project_name, project_presets,
                         global_presets, kg, yield_func, genre=genre)

        # 根据 mode_config 设置默认值
        self.max_rounds_per_dimension = (
            max_rounds_per_dimension if max_rounds_per_dimension is not None
            else self.mode_config["max_rounds_review"]
        )
        self.score_threshold = (
            score_threshold if score_threshold is not None
            else self.mode_config["score_threshold"]
        )

        # 审校维度（全部启用）
        self._dimensions = list(_ALL_REVIEW_DIMENSIONS)

        self._current_dimension = 0
        self._dimensions_done: List[str] = []

    # ---- 读取章节 ----

    def _get_all_chapters(self) -> Dict[int, str]:
        """读取所有章节。"""
        chapters = {}
        d = os.path.join(self.project_dir, "chapters")
        if not os.path.isdir(d):
            return chapters
        for f in os.listdir(d):
            m = re.match(r"第(\d+)章", f)
            if m:
                ch = int(m.group(1))
                with open(os.path.join(d, f), "r", encoding="utf-8") as fh:
                    chapters[ch] = fh.read()
        return chapters

    def _write_atomic(self, path: str, content: str):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(content)
        os.replace(tmp, path)

    # ---- MWR 实现 ----

    def manager_decide(self, round_num: int, last_result: Optional[ReviewResult] = None) -> MWRTask:
        """Manager 决定审校哪个维度。"""
        if last_result and not last_result.all_required_passed:
            # 当前维度还有问题，继续
            dim_key, dim_name, dim_desc = self._dimensions[self._current_dimension]
            return MWRTask(
                action="review",
                dimension=dim_key,
                focus_issues=last_result.issues,
            )

        # 下一个维度
        self._current_dimension += 1
        if self._current_dimension > len(self._dimensions):
            return MWRTask(action="review", dimension="all")

        dim_key, dim_name, dim_desc = self._dimensions[self._current_dimension - 1]
        return MWRTask(action="review", dimension=dim_key)

    async def writer_execute(self, task: MWRTask) -> Draft:
        """Writer 在审校引擎中 = 审校者（读取全书内容，生成审校报告）。"""
        dim_key = task.dimension
        chapters = self._get_all_chapters()

        # 构建审校上下文
        context_parts = []
        kg_ctx = self.kg_adapter.format_character_context()
        if kg_ctx:
            context_parts.append(kg_ctx)
        fs_ctx = self.kg_adapter.format_foreshadowing_context()
        if fs_ctx:
            context_parts.append(fs_ctx)

        # 章节摘要
        ch_summaries = []
        for ch_num in sorted(chapters.keys()):
            content = chapters[ch_num]
            ch_summaries.append(f"第{ch_num}章（{len(content)}字）：{content[:300]}...")
        context_parts.append(f"【章节概览（共{len(chapters)}章）】\n" + "\n".join(ch_summaries[:20]))

        dim_name = dim_key
        dim_desc = ""
        for dk, dn, dd in self._dimensions:
            if dk == dim_key:
                dim_name = dn
                dim_desc = dd
                break

        system_prompt = self.prompts["reviewer_review"] + f"\n\n当前审校维度：{dim_desc}" + "\n\n".join(context_parts)

        # 注入体裁审查维度（InkOS 33维 + Hard Invariants + 疲劳词）
        genre_reviewer = self.genre_adapter.get_reviewer_injection(stage="review")
        if genre_reviewer:
            system_prompt += f"\n\n{genre_reviewer}"

        # 注入反幻觉上下文（开放线索 + 角色状态）
        guard_ctx = self.hallucination_guard.get_writing_context(0)
        if guard_ctx:
            system_prompt += f"\n\n{guard_ctx}"

        # 注入上一轮反馈
        if task.focus_issues:
            feedback = "\n".join(f"- {iss}" for iss in task.focus_issues)
            system_prompt += f"\n\n【上一轮审校反馈】\n{feedback}"

        user_prompt = f"请进行{dim_desc}维度的全局审校。"

        if not self.llm.has_valid_config("reviewer"):
            content = json.dumps({"score": 5.0, "issues": ["未配置 LLM"], "suggestions": [], "fixes": []})
        else:
            content = await self.llm.call("reviewer", system_prompt, user_prompt)

        return Draft(content=content, metadata={"dimension": dim_key})

    async def reviewer_evaluate(self, draft: Draft) -> ReviewResult:
        """Reviewer 评估审校报告（二次确认）。"""
        dim_key = draft.metadata.get("dimension", "")
        issues = []
        suggestions = []
        score = 5.0

        try:
            data = self._extract_json_from_response(draft.content)
            if data:
                score = float(data.get("score", 5.0))
                issues = data.get("issues", [])
                suggestions = data.get("suggestions", [])
        except Exception:
            issues.append("审校报告解析失败")

        # 硬性检查：伏笔维度
        if dim_key == "foreshadowing":
            active_fs = self.kg_adapter.get_active_foreshadowings()
            if active_fs:
                issues.extend([f"伏笔未回收: {fs.get('label', '')}" for fs in active_fs[:5]])

        # 硬性检查：疲劳词（从 draft 内容中检查）
        fatigue_hits = self.genre_adapter.check_fatigue_words(draft.content, threshold=3)
        for hit in fatigue_hits[:3]:
            issues.append(f"疲劳词'{hit['word']}'出现{hit['count']}次")

        # 硬性检查：反幻觉开放线索
        open_threads = self.hallucination_guard.get_open_plot_threads()
        if open_threads and dim_key == "foreshadowing":
            for t in open_threads[:5]:
                issues.append(f"未结线索: {t['name']}（自第{t['introduced_chapter']}章）")

        all_required_passed = score >= self.score_threshold

        self.state.review_add_round(
            round_num=len(self.state.data.get("review", {}).get("rounds", [])) + 1,
            dimension=dim_key, score=score, issues=issues,
        )

        return ReviewResult(
            score=score, issues=issues, suggestions=suggestions,
            all_required_passed=all_required_passed,
        )

    def manager_final_decision(self) -> FinalDecision:
        review_state = self.state.data.get("review", {})
        rounds = review_state.get("rounds", [])
        if rounds:
            last = rounds[-1]
            if last.get("score", 0) >= 5.0:
                return FinalDecision(accepted=True, reason="全局审校评分尚可")
        return FinalDecision(accepted=False, reason="全局审校未通过，需人工审核")

    @staticmethod
    def _extract_json_from_response(text: str):
        """从 LLM 响应中提取 JSON，支持嵌套大括号和 markdown 代码块。"""
        import json
        code_block = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', text, re.DOTALL)
        if code_block:
            try:
                return json.loads(code_block.group(1))
            except Exception:
                pass
        start = text.find('{')
        while start != -1:
            depth = 0
            for i in range(start, len(text)):
                if text[i] == '{':
                    depth += 1
                elif text[i] == '}':
                    depth -= 1
                    if depth == 0:
                        candidate = text[start:i + 1]
                        try:
                            data = json.loads(candidate)
                            if isinstance(data, dict) and "score" in data:
                                return data
                        except Exception:
                            pass
                        break
            start = text.find('{', start + 1)
        try:
            return json.loads(text.strip())
        except Exception:
            return None

    # ---- 公开 API ----

    async def run_review(self) -> Dict:
        """运行全局审校。"""
        self._current_dimension = 0
        results = {}
        for dim_key, dim_name, dim_desc in self._dimensions:
            result = await self.run_mwr_cycle(
                max_rounds=self.max_rounds_per_dimension,
                score_threshold=self.score_threshold,
            )
            results[dim_key] = {
                "name": dim_name,
                "score": result.score,
                "issues": result.issues,
                "passed": result.all_required_passed,
            }
            self.state.data.setdefault("review", {}).setdefault("dimensions_done", []).append(dim_key)
            self.state.save()

        self.state.review_set_status("completed")
        self.state.current_stage = "completed"
        return results

    def get_status(self) -> Dict:
        review_state = self.state.data.get("review", {})
        return {
            "status": review_state.get("status", "pending"),
            "dimensions_done": review_state.get("dimensions_done", []),
            "rounds": review_state.get("rounds", []),
        }
