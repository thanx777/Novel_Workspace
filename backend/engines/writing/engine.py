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
from project_db import ProjectDB


class WritingEngine(BaseEngine):
    """写作引擎：逐章 MWR 循环，写一章 → 检查 → 润色 → 再检查 → 下一章。"""

    def __init__(self, project_dir: str, project_name: str,
                 project_presets: Optional[Dict[str, Dict]] = None,
                 global_presets: Optional[List[Dict]] = None,
                 kg=None, yield_func=None,
                 total_chapters: int = 0,
                 max_polish_rounds: Optional[int] = None,
                 score_threshold: Optional[float] = None,
                 genre: str = ""):
        super().__init__(project_dir, project_name, project_presets,
                         global_presets, kg, yield_func, genre=genre)
        self.total_chapters = total_chapters
        self.max_polish_rounds = max_polish_rounds if max_polish_rounds is not None else self.mode_config["max_polish_rounds"]
        self.score_threshold = score_threshold if score_threshold is not None else self.mode_config["score_threshold"]
        self._current_chapter = 1
        self._polish_count = 0  # 当前章节润色次数
        self._rewrite_count = 0  # 当前章节重写次数
        self._last_valid_ai_score = None  # 上一次有效的AI评审评分
        self._previous_issues = set()  # 上一轮评审的问题集合（用于问题继承机制）

    # ---- 文件路径 ----

    def _chapter_path(self, chapter_num: int) -> str:
        d = os.path.join(self.project_dir, "chapters")
        os.makedirs(d, exist_ok=True)
        return os.path.join(d, f"第{chapter_num}章.txt")

    def _l3_path(self, chapter_num: int) -> str:
        """兼容旧版 L3 章节路径。"""
        return os.path.join(self.project_dir, "outline_L3", f"chapter_{chapter_num}.md")

    def _write_atomic(self, path: str, content: str):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(content)
        os.replace(tmp, path)

    # ---- 读取上下文 ----

    # 中文数字映射（用于章节标题匹配）
    _CN_NUM = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5,
               "六": 6, "七": 7, "八": 8, "九": 9, "十": 10,
               "十一": 11, "十二": 12, "十三": 13, "十四": 14, "十五": 15,
               "十六": 16, "十七": 17, "十八": 18, "十九": 19, "二十": 20,
               "二十一": 21, "二十二": 22, "二十三": 23, "二十四": 24, "二十五": 25,
               "二十六": 26, "二十七": 27, "二十八": 28, "二十九": 29, "三十": 30,
               "三十一": 31, "三十二": 32, "三十三": 33, "三十四": 34, "三十五": 35,
               "三十六": 36, "三十七": 37, "三十八": 38, "三十九": 39, "四十": 40,
               "四十一": 41, "四十二": 42, "四十三": 43, "四十四": 44, "四十五": 45,
               "四十六": 46, "四十七": 47, "四十八": 48, "四十九": 49, "五十": 50,
               "百": 100, "零": 0}

    def _read_chapter_outline(self, chapter_num: int) -> str:
        """读取章节细纲：优先从 L2 合并版中提取对应章节，回退到旧版 L3 文件。"""
        # 1. 尝试从 L2 章节细纲中提取对应章节
        l2_path = os.path.join(self.project_dir, "outline_L2.md")
        if os.path.isfile(l2_path):
            with open(l2_path, "r", encoding="utf-8") as f:
                l2_md = f.read()
            # 匹配 "### 第N章 ..." 到下一个 "### 第M章" 之间的内容
            pattern = rf"###\s*第\s*{chapter_num}\s*章\s*(.*?)(?=\n###\s*第\s*\d+\s*章|\Z)"
            m = re.search(pattern, l2_md, re.DOTALL)
            if not m:
                # 尝试中文数字匹配
                for cn, num in self._CN_NUM.items():
                    if num == chapter_num:
                        pattern_cn = rf"###\s*第\s*{re.escape(cn)}\s*章\s*(.*?)(?=\n###\s*第\s*[\d一二三四五六七八九十百]+\s*章|\Z)"
                        m = re.search(pattern_cn, l2_md, re.DOTALL)
                        if m:
                            break
            if m:
                return f"第{chapter_num}章 " + m.group(1).strip()

        # 2. 回退到旧版 L3 文件
        l3_path = self._l3_path(chapter_num)
        if os.path.isfile(l3_path):
            with open(l3_path, "r", encoding="utf-8") as f:
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
        """Manager 决定：写当前章 / 润色当前章。

        决策逻辑：
        - 第1轮：写新章节
        - 硬性校验未通过 + 润色次数未用尽：润色
        - 硬性校验未通过 + 润色次数用尽：不再重写，由 run_mwr_cycle 的卡住检测结束
        - 硬性校验通过：由 run_mwr_cycle 判断是否达标
        """
        MAX_REWRITES = 2  # 格式问题最多重写2次

        if round_num == 1:
            return MWRTask(action="write", chapter_num=self._current_chapter)

        if last_result and not last_result.all_required_passed:
            # 格式问题（缺少标题、字数不足）需要重写而非润色
            # 注意：issues可能带 [未修复]/[新发现] 后缀，用 in 匹配
            format_issues = [iss for iss in last_result.issues
                            if any(kw in iss for kw in ["缺少章节标题", "字数不足", "章节字数过少"])]

            if format_issues and self._rewrite_count < MAX_REWRITES:
                self._rewrite_count += 1
                return MWRTask(
                    action="write",
                    chapter_num=self._current_chapter,
                    focus_issues=last_result.issues,
                    context=self._format_feedback_context(last_result),
                )

            if self._polish_count < self.max_polish_rounds:
                # 需要润色
                self._polish_count += 1
                return MWRTask(
                    action="polish",
                    chapter_num=self._current_chapter,
                    focus_issues=last_result.issues,
                    context=self._format_feedback_context(last_result),
                )

            # 润色次数用尽且硬性校验仍未通过，标记需人工审核
            self._emit({"status": "chapter_needs_review", "chapter": self._current_chapter})
            return MWRTask(action="accept_current", chapter_num=self._current_chapter)

        # 硬性校验通过但分数不够，尝试润色提升
        if last_result and last_result.all_required_passed and self._polish_count < self.max_polish_rounds:
            self._polish_count += 1
            return MWRTask(
                action="polish",
                chapter_num=self._current_chapter,
                focus_issues=last_result.issues,
                context=self._format_feedback_context(last_result),
            )

        return MWRTask(action="write", chapter_num=self._current_chapter)

    async def writer_execute(self, task: MWRTask) -> Draft:
        """Writer：写一章或润色一章。"""
        ch = task.chapter_num or self._current_chapter

        if task.action == "accept_current":
            # 润色用尽，接受当前内容，不再重写
            content = self._read_chapter(ch)
            return Draft(content=content or "", chapter_num=ch, metadata={"action": "accept"})
        elif task.action == "polish":
            return await self._polish_chapter(ch, task)
        else:
            return await self._write_chapter(ch, task)

    async def _write_chapter(self, ch: int, task: MWRTask) -> Draft:
        """写新章节。"""
        self._emit({"status": "chapter_writing", "chapter": ch})

        # 构建上下文 — KG 为主，memory 为辅，体裁+反幻觉为增强
        context_parts = []

        # ★ 体裁声明放在最前面，确保 LLM 优先遵守
        genre_name = self.genre_adapter.genre_name
        if genre_name and genre_name != "通用":
            inkos = None
            try:
                from ..common.genre_adapter import GenreAdapter
                from genre_data.inkos_data import get_inkos_genre
                inkos = get_inkos_genre(genre_name)
            except Exception:
                pass
            genre_header = f"【体裁要求 — 最高优先级，必须遵守】\n本作品体裁为「{genre_name}」。所有世界观、场景描写、角色行为、术语使用必须严格符合{genre_name}体裁。"
            if inkos:
                setting_terms = inkos.get("settingTerms", [])
                if setting_terms:
                    genre_header += f"\n核心设定词：{'、'.join(setting_terms)}"
                narrative = inkos.get("narrativeGuidance", "")
                if narrative:
                    genre_header += f"\n叙事指导：{narrative}"
            genre_header += f"\n禁止使用与{genre_name}体裁不符的元素（如科幻、赛博朋克、现代科技等）。如果大纲中包含与{genre_name}体裁矛盾的设定，请以{genre_name}体裁为准进行改写。"
            context_parts.append(genre_header)

        # 大纲
        outline = self._read_outline_summary()
        if outline:
            context_parts.append(f"【小说大纲 — 必须严格围绕大纲写作，禁止偏离】\n{outline}")

        # 章节细纲（从 L2 提取或旧版 L3）
        ch_outline = self._read_chapter_outline(ch)
        if ch_outline:
            context_parts.append(f"【本章细纲】\n{ch_outline}")

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

        system_prompt = self.prompts["writer_writing"] + "\n\n" + "\n\n".join(context_parts)
        word_min = self.mode_config['word_count_min']
        word_max = self.mode_config['word_count_max']
        user_prompt = f"请写第{ch}章。严格按照细纲和大纲写作，不要偏离主线。\n\n【字数硬性要求】正文必须达到 {word_min}-{word_max} 字，不足 {word_min} 字视为不合格。请充分展开场景描写、对话、心理活动和动作细节，确保篇幅达标。"

        if not self.llm.has_valid_config("writer"):
            content = f"# 第{ch}章\n\n（未配置 LLM，占位内容）"
        else:
            content = await self.llm.call("writer", system_prompt, user_prompt)

        # 落盘
        self._write_atomic(self._chapter_path(ch), content)

        # 更新反幻觉追踪器
        known_names = [c.get("label", "") for c in self.kg_adapter.get_characters()]
        self.hallucination_guard.update_from_chapter(content, ch, known_names)

        # 写入数据库（唯一入口）
        self._upsert_chapter_to_db(ch, content, status="drafted")

        self._emit({"status": "chapter_written", "chapter": ch})
        return Draft(content=content, chapter_num=ch, metadata={"action": "write"})

    async def _polish_chapter(self, ch: int, task: MWRTask) -> Draft:
        """润色已有章节。"""
        self._emit({"status": "chapter_polishing", "chapter": ch, "polish_round": self._polish_count})

        original = self._read_chapter(ch)
        if not original:
            return await self._write_chapter(ch, task)

        context_parts = []

        # ★ 体裁声明放在最前面
        genre_name = self.genre_adapter.genre_name
        if genre_name and genre_name != "通用":
            context_parts.append(f"【体裁要求 — 最高优先级，必须遵守】\n本作品体裁为「{genre_name}」。润色时必须确保内容符合{genre_name}体裁，禁止出现科幻、赛博朋克等不符元素。")

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

        system_prompt = self.prompts["writer_polish"] + "\n\n" + "\n\n".join(context_parts)
        user_prompt = (
            f"请润色第{ch}章。根据审查反馈修改，保持故事连贯性。\n\n"
            f"--- 原文 ---\n{original}\n--- 原文结束 ---"
        )

        if not self.llm.has_valid_config("writer"):
            content = original
        else:
            content = await self.llm.call("writer", system_prompt, user_prompt)

        # 内容变空/大幅缩水检测和回退
        if not content or not content.strip():
            self._emit({"status": "warning", "message": f"第{ch}章润色后内容为空，回退到原文"})
            content = original
        else:
            original_cn = len(re.findall(r'[\u4e00-\u9fff]', original))
            new_cn = len(re.findall(r'[\u4e00-\u9fff]', content))
            if new_cn < original_cn * 0.5 and original_cn > 500:
                self._emit({"status": "warning", "message": f"第{ch}章润色后字数大幅缩水({new_cn}←{original_cn})，回退到原文"})
                content = original

        # 落盘
        self._write_atomic(self._chapter_path(ch), content)

        # 更新反幻觉追踪器
        known_names = [c.get("label", "") for c in self.kg_adapter.get_characters()]
        self.hallucination_guard.update_from_chapter(content, ch, known_names)

        # 更新数据库（唯一入口）
        self._upsert_chapter_to_db(ch, content, status="polished")

        self._emit({"status": "chapter_polished", "chapter": ch})
        return Draft(content=content, chapter_num=ch, metadata={"action": "polish"})

    async def reviewer_evaluate(self, draft: Draft) -> ReviewResult:
        """Reviewer：硬性层（KG验证 + 格式校验 + 疲劳词 + 反幻觉本地检查）+ AI 层。

        问题继承机制：区分 persistent_issues（上轮就有，必须修）和 fresh_issues（本轮新出，给1轮缓冲）。
        - all_required_passed 只看 persistent_issues
        - fresh_issues 不阻塞通过，但记录到 _previous_issues 供下轮检查
        """
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
            if hit.get("is_setting"):
                issues.append(f"设定词'{hit['word']}'出现{hit['count']}次（建议适当替换部分为同义表达）")
            else:
                issues.append(f"疲劳词'{hit['word']}'出现{hit['count']}次（≥3次扣分）")

        # 5. AI痕迹本地检查（ConsistencyChecker）
        ai_issues = self.hallucination_guard.quick_local_check(content)
        issues.extend(ai_issues)

        # 6. 字数检查（使用中文字数，与 FormatValidator 一致）
        word_count = len(re.findall(r'[\u4e00-\u9fff]', content))
        if word_count < 1000:
            issues.append(f"章节字数过少: {word_count} 字")

        # === AI 层 ===
        score = 0.0
        suggestions = []
        if self.llm.has_valid_config("reviewer"):
            score, ai_issues, ai_suggestions = await self._ai_review(ch, content)
            # 解析失败时复用上次有效评分，避免评分突降导致无效润色
            if "AI 评审解析失败" in ai_issues and self._last_valid_ai_score is not None:
                score = self._last_valid_ai_score
                ai_issues = [f"AI评审解析失败，复用上次评分{score}"]
            elif "AI 评审解析失败" not in ai_issues:
                self._last_valid_ai_score = score
            issues.extend(ai_issues)
            suggestions.extend(ai_suggestions)
        else:
            score = 6.0 if len(hallucination_warnings) == 0 else 3.0

        # === 问题继承机制 ===
        # 区分 persistent_issues（上轮就有，必须修）和 fresh_issues（本轮新出，给1轮缓冲）
        current_issues_set = set(issues)
        persistent_issues = [iss for iss in issues if iss in self._previous_issues]
        fresh_issues = [iss for iss in issues if iss not in self._previous_issues]

        # fresh_issues 不阻塞通过，但记录到 _previous_issues 供下轮检查
        # persistent_issues 必须修复才允许通过
        has_persistent_blockers = len(persistent_issues) > 0

        # all_required_passed 只看 persistent_issues + 硬性底线
        all_required_passed = (
            not has_persistent_blockers
            and len(hallucination_warnings) == 0
            and word_count >= 1000
            and format_result.get("passed", True)
        )

        # 评分调整：fresh_issues 不额外扣分（已包含在AI评分中，这里不重复惩罚）
        # 但如果有 persistent_issues，额外扣0.5分/个（上限2分）
        if persistent_issues:
            penalty = min(len(persistent_issues) * 0.5, 2.0)
            score = max(score - penalty, 0.0)

        # 更新 _previous_issues：本轮所有问题都成为下轮的"老问题"
        self._previous_issues = current_issues_set

        # 在 issues 中标注类型，方便前端展示
        annotated_issues = []
        for iss in persistent_issues:
            annotated_issues.append(f"{iss} [未修复]")
        for iss in fresh_issues:
            annotated_issues.append(f"{iss} [新发现]")

        # 记录状态
        action = draft.metadata.get("action", "write")
        self.state.writing_add_round(
            round_num=len(self.state.data.get("writing", {}).get("rounds", [])) + 1,
            chapter=ch, action=action, score=score, issues=annotated_issues,
        )

        return ReviewResult(
            score=score, issues=annotated_issues, suggestions=suggestions,
            all_required_passed=all_required_passed,
            hallucination_warnings=hallucination_warnings,
        )

    async def _ai_review(self, ch: int, content: str) -> tuple:
        """AI 评审章节（注入体裁审查维度）。"""
        system_prompt = self.prompts["reviewer_writing"]

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
            data = self._extract_json_from_response(resp)
            if data:
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

    @staticmethod
    def _extract_json_from_response(text: str):
        """从 LLM 响应中提取 JSON，支持嵌套大括号和 markdown 代码块。"""
        import json
        # 1. 尝试从 ```json ... ``` 代码块中提取（贪婪匹配，支持嵌套JSON）
        code_block = re.search(r'```(?:json)?\s*(\{.+\})\s*```', text, re.DOTALL)
        if code_block:
            try:
                return json.loads(code_block.group(1))
            except Exception:
                pass
        # 2. 查找包含 "score" 的最外层 JSON 对象（支持嵌套）
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
        # 3. 直接尝试解析整个响应
        try:
            return json.loads(text.strip())
        except Exception:
            return None

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

    # 常见误判词黑名单：这些词虽能匹配"名词+对话动词"模式，但不是角色名
    _FALSE_POSITIVE_NAMES = frozenset({
        "有事", "点头", "不知", "但他知", "也不知", "心中", "忽然", "突然",
        "只见", "只是", "但是", "然而", "虽然", "不过", "而且", "因此",
        "于是", "可是", "难道", "果然", "居然", "竟然", "显然", "似乎",
        "好像", "大概", "也许", "几乎", "简直", "反而", "尽管", "何况",
        "况且", "甚至", "尤其", "特别", "非常", "十分", "相当", "极其",
        "格外", "分外", "异常", "颇为", "稍许", "略微", "稍微", "些许",
        "若干", "多少", "几许", "何等", "多么", "何其", "至极", "透顶",
        "万分", "极度", "早已", "早已知", "明知", "方知", "才知", "已知",
        "他知", "你知", "我知", "谁知", "怎知", "安知", "殊不知",
        # 副词+对话动词误判
        "低声", "高声", "大声", "小声", "轻声", "沉声", "冷声", "柔声",
        "缓缓", "淡淡", "默默", "静静", "冷冷", "微微",
        "低头", "抬头", "摇头", "转身",
        # 新增误判词
        "皱眉", "分身", "虚弱", "尖叫", "苦笑", "冷哼", "叹息",
        "他低", "他轻", "她虚", "有人",
    })

    def _extract_chapter_title(self, content: str) -> str:
        """从内容中提取章节标题，如 '# 第一章 灵根觉醒' → '灵根觉醒'。
        跳过 ---PREV: / ---CAST: 等上下文标记行，找到第一个真正的标题行。"""
        for line in content.strip().split("\n"):
            line = line.strip()
            if not line:
                continue
            # 跳过上下文标记行
            if line.startswith("---PREV:") or line.startswith("---CAST:") or line.startswith("---"):
                continue
            # 匹配 markdown 标题 + "第N章" 格式
            m = re.match(r"^#+\s*第[一二三四五六七八九十百千\d]+章\s*(.*)", line)
            if m and m.group(1).strip():
                return m.group(1).strip()
            # 匹配纯 "第N章 标题" 格式
            m = re.match(r"^第[一二三四五六七八九十百千\d]+章\s+(.*)", line)
            if m and m.group(1).strip():
                return m.group(1).strip()
            # 匹配 markdown 标题（无"第N章"前缀）
            m = re.match(r"^#+\s*(.+)", line)
            if m and m.group(1).strip():
                title = m.group(1).strip()
                # 去掉"第N章"前缀
                title = re.sub(r"^第[一二三四五六七八九十百千\d]+章\s*", "", title)
                return title.strip() or f"第N章"
            # 非标题行，跳过
            continue
        return f"第N章"

    def _upsert_chapter_to_db(self, chapter_num: int, content: str, status: str = "drafted", score: float = 0.0):
        """将章节信息写入 SQLite 数据库（唯一入口）。

        status 流转：drafted → polished → completed
        - drafted: 首次写入（_write_chapter）
        - polished: 润色后（_polish_chapter）
        - completed: MWR循环结束后（write_chapter 最终同步）
        """
        try:
            db = ProjectDB(self.project_name)
            title = self._extract_chapter_title(content)
            # 如果标题为空或回退到"第N章"，使用正确的章节号
            if not title.strip() or title.strip() == "第N章":
                title = f"第{chapter_num}章"
            summary = content[:100].replace("\n", " ").strip()
            # 统一使用中文字数计算（与 FormatValidator 一致）
            word_count = len(re.findall(r'[\u4e00-\u9fff]', content))
            # 优先从大纲生成的标题映射中获取标题
            titles_path = os.path.join(self.project_dir, "chapter_titles.json")
            if os.path.isfile(titles_path):
                try:
                    import json as _json
                    with open(titles_path, "r", encoding="utf-8") as f:
                        titles_map = _json.load(f)
                    mapped_title = titles_map.get(str(chapter_num))
                    if mapped_title:
                        title = f"第{chapter_num}章 {mapped_title}"
                except Exception:
                    pass
            db.upsert_chapter(chapter_num, title=title, summary=summary, status=status, word_count=word_count)
            db.close()
        except Exception as e:
            self._emit({"status": "warning", "message": f"同步章节到数据库失败: {e}"})

    def _extract_character_names(self, text: str) -> List[str]:
        """从文本中提取可能的人名。"""
        names = set()
        # 匹配2-3字中文名，前面必须是句首/标点/换行/空格，后面紧跟引号或"X道："格式
        # 这样避免"顾寒低声说道"匹配出"寒低声"等副词误判
        for m in re.finditer(
            r'(?:^|(?<=[，。！？；：、\n\s]))[\u4e00-\u9fff]{2,3}(?=[""「\'』]|说道|道：|喊道|叫道|笑道|怒道|叹道|想道|问道|答道)',
            text,
        ):
            name = m.group().strip()
            if not name or name in self._FALSE_POSITIVE_NAMES:
                continue
            # 3字名字：如果后2字在黑名单中，也排除（如"他低声"的后2字"低声"在黑名单中）
            if len(name) == 3 and name[1:] in self._FALSE_POSITIVE_NAMES:
                continue
            names.add(name)
        return list(names)

    # ---- 公开 API ----

    async def write_chapter(self, chapter_num: int) -> Dict:
        """写指定章节（MWR 循环 + AI 摄取到知识图谱）。"""
        self._current_chapter = chapter_num
        self._polish_count = 0
        self._rewrite_count = 0
        self._last_valid_ai_score = None
        self._previous_issues = set()  # 每章重置问题继承
        result = await self.run_mwr_cycle(
            max_rounds=self.mode_config["max_rounds_writing"],
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

        # 最终同步章节到数据库（确保 status 和 score 正确）
        self._upsert_chapter_to_db(chapter_num, content or "",
                                    status="completed", score=result.score)

        return {"chapter": chapter_num, "score": result.score, "issues": result.issues}

    async def write_all(self, start_chapter: int = 1) -> Dict:
        """从指定章节开始逐章写作。"""
        # 如果 total_chapters 未确定，从多种来源推断
        if self.total_chapters <= 0:
            try:
                from project_db import ProjectDB
                db = ProjectDB(self.project_name)
                info = db.get_project()
                self.total_chapters = info.get("total_chapters", 0)
                db.close()
            except Exception:
                pass
            # 从 L2 大纲推断
            if self.total_chapters <= 0:
                l2_path = os.path.join(self.project_dir, "outline_L2.md")
                if os.path.isfile(l2_path):
                    with open(l2_path, "r", encoding="utf-8") as f:
                        l2_md = f.read()
                    max_ch = 0
                    for m in re.finditer(r"###\s*第\s*(\d+)\s*章", l2_md):
                        ch = int(m.group(1))
                        if ch > max_ch:
                            max_ch = ch
                    if max_ch > 0:
                        self.total_chapters = max_ch
            # 从已有章节文件推断
            if self.total_chapters <= 0:
                chapters_dir = os.path.join(self.project_dir, "chapters")
                if os.path.isdir(chapters_dir):
                    max_ch = 0
                    for fname in os.listdir(chapters_dir):
                        m = re.match(r"第(\d+)章\.txt$", fname)
                        if m:
                            ch = int(m.group(1))
                            if ch > max_ch:
                                max_ch = ch
                    if max_ch > 0:
                        self.total_chapters = max_ch
            if self.total_chapters <= 0:
                self._emit({"status": "error", "message": "章节数未确定，请先生成大纲"})
                return {"success": False, "error": "total_chapters not set"}

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
            completed_count = ch - start_chapter + 1
            self._emit({"status": "chapter_completed", "chapter": ch,
                         "progress": f"{ch}/{self.total_chapters}",
                         "total": self.total_chapters, "completed": completed_count})

            # 连续低分检测：如果连续多章评分低于阈值，发出警告但继续写作
            if r.get("score", 0) < self.score_threshold:
                consecutive_failures += 1
                if consecutive_failures >= max_consecutive_failures:
                    self._emit({"status": "writing_warning", "reason": f"连续{max_consecutive_failures}章评分低于阈值，继续写作"})
                    consecutive_failures = 0
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
