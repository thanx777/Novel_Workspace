"""写作引擎 — MWR 循环逐章写作 + 内置润色，每轮产出一章。"""

import os
import re
import json
from typing import Dict, List, Optional

from ..common.base_engine import BaseEngine, MWRTask, Draft, ReviewResult, FinalDecision
from ..common.llm_client import LLMClient
from ..common.kg_adapter import KGAdapter
from ..common.state import EngineState
from ..common.prompts import (
    MANAGER_SYSTEM, WRITER_SYSTEM_WRITING, WRITER_SYSTEM_POLISH,
    REVIEWER_SYSTEM_WRITING, CHAT_SYSTEM, OUTPUT_FORMAT_CONSTRAINT,
)


class WritingEngine(BaseEngine):
    """写作引擎：逐章 MWR 循环，写一章 → 检查 → 润色 → 再检查 → 下一章。"""

    def __init__(self, project_dir: str, project_name: str,
                 project_presets: Optional[Dict[str, Dict]] = None,
                 global_presets: Optional[List[Dict]] = None,
                 kg=None, yield_func=None,
                 total_chapters: int = 100,
                 max_polish_rounds: int = 3,
                 score_threshold: float = 7.0,
                 genre: str = ""):
        super().__init__(project_dir, project_name, project_presets,
                         global_presets, kg, yield_func, genre=genre)
        self.total_chapters = total_chapters
        self.max_polish_rounds = max_polish_rounds
        self.score_threshold = score_threshold
        self._current_chapter = 1
        self._polish_count = 0  # 当前章节润色次数

    # ---- 文件路径 ----

    def _chapter_path(self, chapter_num: int) -> str:
        d = os.path.join(self.project_dir, "chapters")
        os.makedirs(d, exist_ok=True)
        return os.path.join(d, f"第{chapter_num}章.txt")

    def _l3_path(self, chapter_num: int) -> str:
        """与旧 OutlinePipeline / v2_api 保持一致的 L3 章节路径。"""
        return os.path.join(self.project_dir, "outline_L3", f"chapter_{chapter_num}.md")

    def _write_atomic(self, path: str, content: str):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(content)
        os.replace(tmp, path)

    # ---- 读取上下文 ----

    def _read_l3_outline(self, chapter_num: int) -> str:
        path = self._l3_path(chapter_num)
        if os.path.isfile(path):
            with open(path, "r", encoding="utf-8") as f:
                return f.read()
        return ""

    def _read_chapter(self, chapter_num: int) -> str:
        path = self._chapter_path(chapter_num)
        if os.path.isfile(path):
            with open(path, "r", encoding="utf-8") as f:
                return f.read()
        return ""

    def _read_recent_chapters(self, n: int = 3) -> str:
        """读取最近 n 章的结尾。"""
        parts = []
        start = max(1, self._current_chapter - n)
        for ch in range(start, self._current_chapter):
            content = self._read_chapter(ch)
            if content:
                parts.append(f"【第{ch}章 结尾】...{content[-500:]}")
        return "\n\n".join(parts)

    def _read_global_memory(self) -> str:
        """读取全局记忆（用户笔记）。"""
        path = os.path.join(self.project_dir, "memory.md")
        if os.path.isfile(path):
            with open(path, "r", encoding="utf-8") as f:
                return f.read()[:4000]
        return ""

    def _read_fused_memory(self, chapter_num: int) -> str:
        """融合记忆：KG 结构化实体 + 人物设定 + 用户笔记 + 反幻觉上下文。

        KG 为主（角色/伏笔/场景/世界观/剧情线/前情提要），
        memory 为辅（用户手动笔记），
        反幻觉为补充（角色状态速查 + 待回收伏笔）。
        """
        parts = []

        # 1. KG 结构化实体（角色、伏笔、世界观、场景、剧情线、前情提要）
        kg_ctx = self.kg_adapter.get_chapter_context(chapter_num)
        if kg_ctx:
            parts.append(kg_ctx)

        # 2. 反幻觉上下文（角色状态速查 + 待回收伏笔）
        guard_ctx = self.hallucination_guard.get_writing_context(chapter_num)
        if guard_ctx:
            parts.append(guard_ctx)

        # 3. 人物设定（characters.md — KG 中可能没有完整设定，这里补充）
        chars = self._read_characters()
        if chars:
            kg_chars = self.kg_adapter.get_characters()
            if kg_chars:
                parts.append(f"【人物详细设定（补充 KG 角色信息）— 禁止擅自新增角色】\n{chars}")
            else:
                parts.append(f"【人物设定 — 禁止擅自新增角色】\n{chars}")

        # 4. 用户笔记（memory.md — 自由文本，用户手动维护）
        memory = self._read_global_memory()
        if memory:
            parts.append(f"【用户笔记（作者补充的创作备忘）】\n{memory}")

        if not parts:
            return ""
        return "\n\n".join(parts)

    def _read_outline_summary(self) -> str:
        """读取大纲摘要。"""
        path = os.path.join(self.project_dir, "outline_L1.md")
        if os.path.isfile(path):
            with open(path, "r", encoding="utf-8") as f:
                return f.read()[:3000]
        return ""

    def _read_characters(self) -> str:
        """读取人物设定。"""
        path = os.path.join(self.project_dir, "characters.md")
        if os.path.isfile(path):
            with open(path, "r", encoding="utf-8") as f:
                return f.read()[:2000]
        return ""

    # ---- MWR 实现 ----

    def manager_decide(self, round_num: int, last_result: Optional[ReviewResult] = None) -> MWRTask:
        """Manager 决定：写新章 / 润色当前章 / 跳过。"""
        if last_result and not last_result.all_required_passed and self._polish_count < self.max_polish_rounds:
            # 需要润色
            self._polish_count += 1
            return MWRTask(
                action="polish",
                chapter_num=self._current_chapter,
                focus_issues=last_result.issues,
                context=self._format_feedback_context(last_result),
            )

        # 写新章（或润色次数用尽后跳到下一章）
        if last_result and not last_result.all_required_passed:
            # 润色次数用尽，标记需人工审核，继续下一章
            self._emit({"status": "chapter_needs_review", "chapter": self._current_chapter})

        self._current_chapter = self._next_unwritten_chapter()
        self._polish_count = 0
        if self._current_chapter > self.total_chapters:
            return MWRTask(action="review", chapter_num=0)  # 全部写完

        return MWRTask(action="write", chapter_num=self._current_chapter)

    async def writer_execute(self, task: MWRTask) -> Draft:
        """Writer：写一章或润色一章。"""
        ch = task.chapter_num or self._current_chapter

        if task.action == "polish":
            return await self._polish_chapter(ch, task)
        else:
            return await self._write_chapter(ch, task)

    async def _write_chapter(self, ch: int, task: MWRTask) -> Draft:
        """写新章节。"""
        self._emit({"status": "chapter_writing", "chapter": ch})

        # 构建上下文 — KG 为主，memory 为辅，体裁+反幻觉为增强
        context_parts = []

        # 大纲
        outline = self._read_outline_summary()
        if outline:
            context_parts.append(f"【小说大纲 — 必须严格围绕大纲写作，禁止偏离】\n{outline}")

        # L3 细纲
        l3 = self._read_l3_outline(ch)
        if l3:
            context_parts.append(f"【本章细纲】\n{l3}")

        # 融合记忆：KG 结构化实体 + 反幻觉上下文 + 人物设定 + 用户笔记
        memory_block = self._read_fused_memory(ch)
        if memory_block:
            context_parts.append(memory_block)

        # 前文
        recent = self._read_recent_chapters(3)
        if recent:
            context_parts.append(f"【最近章节结尾 — 必须自然衔接】\n{recent}")

        # 体裁注入：InkOS 规范 + Anti-AI 规范 + 爽点结构 + Strand 节奏
        genre_injection = self.genre_adapter.get_writer_injection(stage="writing")
        if genre_injection:
            context_parts.append(genre_injection)

        system_prompt = WRITER_SYSTEM_WRITING + "\n\n" + "\n\n".join(context_parts)
        user_prompt = f"请写第{ch}章。严格按照细纲和大纲写作，不要偏离主线。字数 3000-5000 字。"

        if not self.llm.has_valid_config("writer"):
            content = f"# 第{ch}章\n\n（未配置 LLM，占位内容）"
        else:
            content = await self.llm.call("writer", system_prompt, user_prompt)

        # 落盘
        self._write_atomic(self._chapter_path(ch), content)

        # 更新反幻觉追踪器
        known_names = [c.get("label", "") for c in self.kg_adapter.get_characters()]
        self.hallucination_guard.update_from_chapter(content, ch, known_names)

        self._emit({"status": "chapter_written", "chapter": ch})
        return Draft(content=content, chapter_num=ch, metadata={"action": "write"})

    async def _polish_chapter(self, ch: int, task: MWRTask) -> Draft:
        """润色已有章节。"""
        self._emit({"status": "chapter_polishing", "chapter": ch, "polish_round": self._polish_count})

        original = self._read_chapter(ch)
        if not original:
            return await self._write_chapter(ch, task)

        context_parts = []

        # 大纲
        outline = self._read_outline_summary()
        if outline:
            context_parts.append(f"【小说大纲】\n{outline}")

        # 融合记忆
        memory_block = self._read_fused_memory(ch)
        if memory_block:
            context_parts.append(memory_block)

        # 体裁注入（润色也需要遵守 InkOS 规范和 Anti-AI 规范）
        genre_injection = self.genre_adapter.get_writer_injection(stage="writing")
        if genre_injection:
            context_parts.append(genre_injection)

        # 审查反馈
        if task.focus_issues:
            feedback = "\n".join(f"- {iss}" for iss in task.focus_issues)
            context_parts.append(f"【审查反馈 — 请针对这些问题修改】\n{feedback}")

        system_prompt = WRITER_SYSTEM_POLISH + "\n\n" + "\n\n".join(context_parts)
        user_prompt = (
            f"请润色第{ch}章。根据审查反馈修改，保持故事连贯性。\n\n"
            f"--- 原文 ---\n{original}\n--- 原文结束 ---"
        )

        if not self.llm.has_valid_config("writer"):
            content = original
        else:
            content = await self.llm.call("writer", system_prompt, user_prompt)

        # 落盘
        self._write_atomic(self._chapter_path(ch), content)

        # 更新反幻觉追踪器
        known_names = [c.get("label", "") for c in self.kg_adapter.get_characters()]
        self.hallucination_guard.update_from_chapter(content, ch, known_names)

        self._emit({"status": "chapter_polished", "chapter": ch})
        return Draft(content=content, chapter_num=ch, metadata={"action": "polish"})

    async def reviewer_evaluate(self, draft: Draft) -> ReviewResult:
        """Reviewer：硬性层（KG验证 + 格式校验 + 疲劳词 + 反幻觉本地检查）+ AI 层。"""
        ch = draft.chapter_num
        content = draft.content

        issues = []
        hallucination_warnings = []

        # === 硬性层 ===

        # 1. 人名校验（KG）
        names = self._extract_character_names(content)
        if names:
            unknown = self.kg_adapter.validate_character_names(names)
            if unknown:
                hallucination_warnings.extend([f"疑似幻觉角色: {n}" for n in unknown])
                issues.extend(hallucination_warnings)

        # 2. 伏笔 ID 匹配（KG）
        fs_ids = re.findall(r"FS-\d+", content)
        if fs_ids:
            unknown_fs = self.kg_adapter.validate_foreshadowing_ids(fs_ids)
            if unknown_fs:
                hallucination_warnings.extend([f"未知伏笔 ID: {fid}" for fid in unknown_fs])

        # 3. 格式校验（FormatValidator）
        format_result = self.hallucination_guard.validate_chapter(content, ch)
        if not format_result.get("passed", True):
            issues.extend(format_result.get("issues", []))

        # 4. 疲劳词本地检查（GenreAdapter）
        fatigue_hits = self.genre_adapter.check_fatigue_words(content, threshold=3)
        for hit in fatigue_hits:
            issues.append(f"疲劳词'{hit['word']}'出现{hit['count']}次（≥3次扣分）")

        # 5. AI痕迹本地检查（ConsistencyChecker）
        ai_issues = self.hallucination_guard.quick_local_check(content)
        issues.extend(ai_issues)

        # 6. 字数检查
        word_count = len(content)
        if word_count < 1000:
            issues.append(f"章节字数过少: {word_count} 字")

        # === AI 层 ===
        score = 0.0
        suggestions = []
        if self.llm.has_valid_config("reviewer"):
            score, ai_issues, ai_suggestions = await self._ai_review(ch, content)
            issues.extend(ai_issues)
            suggestions.extend(ai_suggestions)
        else:
            score = 6.0 if len(hallucination_warnings) == 0 else 3.0

        all_required_passed = (
            len(hallucination_warnings) == 0
            and word_count >= 1000
            and format_result.get("passed", True)
        )

        # 记录状态
        action = draft.metadata.get("action", "write")
        self.state.writing_add_round(
            round_num=len(self.state.data.get("writing", {}).get("rounds", [])) + 1,
            chapter=ch, action=action, score=score, issues=issues,
        )

        return ReviewResult(
            score=score, issues=issues, suggestions=suggestions,
            all_required_passed=all_required_passed,
            hallucination_warnings=hallucination_warnings,
        )

    async def _ai_review(self, ch: int, content: str) -> tuple:
        """AI 评审章节（注入体裁审查维度）。"""
        system_prompt = REVIEWER_SYSTEM_WRITING

        # 注入 KG 上下文
        kg_ctx = self.kg_adapter.get_chapter_context(ch)
        if kg_ctx:
            system_prompt += f"\n\n{kg_ctx}"

        # 注入体裁审查维度（InkOS 33维 + Hard Invariants + 疲劳词清单）
        genre_reviewer = self.genre_adapter.get_reviewer_injection(stage="writing")
        if genre_reviewer:
            system_prompt += f"\n\n{genre_reviewer}"

        user_prompt = f"请审校第{ch}章：\n\n{content[:6000]}"

        try:
            resp = await self.llm.call("reviewer", system_prompt, user_prompt)
            json_match = re.search(r'\{[^{}]*"score"[^{}]*\}', resp, re.DOTALL)
            if json_match:
                data = json.loads(json_match.group())
                return float(data.get("score", 5.0)), data.get("issues", []), data.get("suggestions", [])
        except Exception:
            pass
        return 5.0, ["AI 评审解析失败"], []

    def manager_final_decision(self) -> FinalDecision:
        writing_state = self.state.data.get("writing", {})
        rounds = writing_state.get("rounds", [])
        if rounds:
            last = rounds[-1]
            if last.get("score", 0) >= 5.0:
                return FinalDecision(accepted=True, reason="评分尚可，接受当前章节")
        return FinalDecision(accepted=False, reason="章节质量不达标，需人工审核")

    # ---- 辅助 ----

    def _next_unwritten_chapter(self) -> int:
        """找到下一个未写的章节。"""
        completed = self.state.data.get("writing", {}).get("completed_chapters", [])
        for ch in range(1, self.total_chapters + 1):
            if ch not in completed and not os.path.isfile(self._chapter_path(ch)):
                return ch
        return self.total_chapters + 1

    def _format_feedback_context(self, result: ReviewResult) -> str:
        parts = []
        if result.issues:
            parts.append("问题：\n" + "\n".join(f"- {i}" for i in result.issues))
        if result.hallucination_warnings:
            parts.append("幻觉警告：\n" + "\n".join(f"- {w}" for w in result.hallucination_warnings))
        return "\n\n".join(parts)

    def _extract_character_names(self, text: str) -> List[str]:
        """从文本中提取可能的人名。"""
        names = set()
        for m in re.finditer(r"[\u4e00-\u9fff]{2,4}(?=说道|道|喊|叫|笑|怒|叹|想|问|答)", text):
            name = m.group()
            if len(name) >= 2:
                names.add(name)
        return list(names)

    # ---- 公开 API ----

    async def write_chapter(self, chapter_num: int) -> Dict:
        """写指定章节（MWR 循环 + AI 摄取到知识图谱）。"""
        self._current_chapter = chapter_num
        self._polish_count = 0
        result = await self.run_mwr_cycle(
            max_rounds=1 + self.max_polish_rounds,
            score_threshold=self.score_threshold,
        )
        self.state.writing_complete_chapter(chapter_num)

        # AI 驱动的 KG 摄取（替代旧的简单 add_chapter_node）
        content = self._read_chapter(chapter_num)
        if content:
            await self.kg_adapter.ai_ingest_chapter(
                chapter_num, content,
                llm_client=self.llm,
                emit=self._emit,
            )
            # 更新反幻觉追踪器的记忆
            self.hallucination_guard.update_memory(content, chapter_num)

        return {"chapter": chapter_num, "score": result.score, "issues": result.issues}

    async def write_all(self, start_chapter: int = 1) -> Dict:
        """从指定章节开始逐章写作。"""
        results = []
        consecutive_failures = 0
        max_consecutive_failures = 5

        for ch in range(start_chapter, self.total_chapters + 1):
            # 检查是否已被用户取消
            if self.cancelled:
                self._emit({"status": "writing_cancelled", "chapter": ch, "reason": "用户取消"})
                break

            r = await self.write_chapter(ch)
            results.append(r)
            self._emit({"status": "chapter_completed", "chapter": ch, "progress": f"{ch}/{self.total_chapters}"})

            # 连续失败检测：如果连续多章评分低于阈值，提前终止
            if r.get("score", 0) < self.score_threshold or r.get("issues"):
                consecutive_failures += 1
                if consecutive_failures >= max_consecutive_failures:
                    self._emit({"status": "writing_stopped", "reason": f"连续{max_consecutive_failures}章质量不达标，停止写作"})
                    break
            else:
                consecutive_failures = 0

        self.state.writing_set_status("completed")
        self.state.current_stage = "review"
        return {"chapters_written": len(results), "results": results}

    def get_status(self) -> Dict:
        writing_state = self.state.data.get("writing", {})
        completed = writing_state.get("completed_chapters", [])
        return {
            "status": writing_state.get("status", "pending"),
            "current_chapter": writing_state.get("current_chapter", 0),
            "total_chapters": self.total_chapters,
            "completed_chapters": completed,
            "progress": f"{len(completed)}/{self.total_chapters}",
        }

    async def chat(self, message: str, chapter_num: int = 0) -> str:
        """AI 对话（带章节上下文）。"""
        context_parts = []
        if chapter_num:
            content = self._read_chapter(chapter_num)
            if content:
                context_parts.append(f"当前第{chapter_num}章：\n{content[:3000]}")
        kg_ctx = self.kg_adapter.get_chapter_context(chapter_num or self._current_chapter)
        if kg_ctx:
            context_parts.append(kg_ctx)
        system_prompt = CHAT_SYSTEM
        if context_parts:
            system_prompt += "\n\n" + "\n\n".join(context_parts)
        return await self.llm.call("chat", system_prompt, message)
