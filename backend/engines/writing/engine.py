"""写作引擎 — MWR 循环逐章写作 + 内置润色，每轮产出一章。"""

import os
import re
import json
from typing import Dict, List, Optional

from ..common.base_engine import BaseEngine, MWRTask, Draft, ReviewResult, FinalDecision
from ..common.llm_client import LLMClient, LLMError
from ..common.kg_adapter import KGAdapter
from ..common.utils import extract_json_from_response, extract_chapter_title
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
        self._ineffective_polish_count = 0  # 连续无效润色次数

    # ---- 文件路径 ----

    def _l3_path(self, chapter_num: int) -> str:
        """兼容旧版 L3 章节路径。"""
        return os.path.join(self.project_dir, "outline_L3", f"chapter_{chapter_num}.md")

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

    # 全局性问题关键词 — 这些问题无法通过段落级编辑修复，需要全文润色
    _GLOBAL_ISSUE_KEYWORDS = [
        "省略号过多", "省略号过多",
        "AI痕迹", "重复句式", "模板化", "万能形容词",
        "说道滥用", "重复描写", "重复模式",
        "疲劳词",
    ]

    # 字数问题关键词 — 需要全文重写扩写
    _WORD_COUNT_ISSUE_KEYWORDS = [
        "字数不足", "字数偏少", "字数过少", "字数严重不足",
    ]

    def _classify_issues(self, issues: list) -> str:
        """分类当前问题，决定润色策略。

        优先解析 Reviewer 输出的 [全局]/[局部]/[字数] 标记，
        回退到关键词匹配。

        Returns:
            "word_count" — 字数不足，需要全文重写扩写
            "global" — 全局问题（AI痕迹/省略号等），需要全文润色
            "local" — 局部问题（衔接/角色矛盾等），段落级润色即可
        """
        # 优先解析 Reviewer 标注的类型标记
        for iss in issues:
            clean = re.sub(r'\s*\[(?:未修复|新发现)\]', '', iss)
            if '[字数]' in clean:
                return "word_count"

        for iss in issues:
            clean = re.sub(r'\s*\[(?:未修复|新发现)\]', '', iss)
            if '[全局]' in clean:
                return "global"

        for iss in issues:
            clean = re.sub(r'\s*\[(?:未修复|新发现)\]', '', iss)
            if '[局部]' in clean:
                return "local"

        # 回退：关键词匹配
        for iss in issues:
            clean = re.sub(r'\s*\[(?:未修复|新发现)\]', '', iss)
            if any(kw in clean for kw in self._WORD_COUNT_ISSUE_KEYWORDS):
                return "word_count"

        global_count = 0
        for iss in issues:
            clean = re.sub(r'\s*\[(?:未修复|新发现)\]', '', iss)
            if any(kw in clean for kw in self._GLOBAL_ISSUE_KEYWORDS):
                global_count += 1

        if global_count > 0:
            return "global"

        return "local"

    def manager_decide(self, round_num: int, last_result: Optional[ReviewResult] = None) -> MWRTask:
        """Manager 决定：写当前章 / 润色当前章 / 全文润色。

        决策逻辑：
        - 第1轮：写新章节
        - 低分(<=4)：全文重写（润色救不了严重幻觉/剧情崩塌）
        - 字数不足：全文重写（不受 MAX_REWRITES 限制）
        - 格式问题（缺标题等）+ 重写次数未用尽：全文重写
        - 全局问题（AI痕迹/省略号等）：全文润色（polish_fulltext）
        - 局部问题（衔接/角色矛盾等）：段落级润色（polish）
        - 润色次数用尽：accept_current
        """
        if round_num == 1:
            return MWRTask(action="write", chapter_num=self._current_chapter)

        if last_result and not last_result.all_required_passed:
            # 低分(<=4)：全文重写（润色修不了严重幻觉/剧情崩塌/新角色违规）
            if last_result.score <= 4.0 and self._rewrite_count < 2:
                self._rewrite_count += 1
                self._emit({"status": "info", "message":
                    f"评分{last_result.score:.1f}过低，跳过润色直接重写"})
                return MWRTask(
                    action="write",
                    chapter_num=self._current_chapter,
                    focus_issues=last_result.issues,
                    context=self._format_feedback_context(last_result),
                )

            # 字数不足：全文重写扩写（不受 MAX_REWRITES 限制）
            word_count_issues = [iss for iss in last_result.issues
                                 if any(kw in iss for kw in self._WORD_COUNT_ISSUE_KEYWORDS)]
            if word_count_issues:
                self._rewrite_count += 1
                return MWRTask(
                    action="write",
                    chapter_num=self._current_chapter,
                    focus_issues=last_result.issues,
                    context=self._format_feedback_context(last_result),
                )

            # 格式问题（缺少标题）+ 重写次数未用尽：全文重写
            format_issues = [iss for iss in last_result.issues
                            if any(kw in iss for kw in ["缺少章节标题"])]

            if format_issues and self._rewrite_count < 2:
                self._rewrite_count += 1
                return MWRTask(
                    action="write",
                    chapter_num=self._current_chapter,
                    focus_issues=last_result.issues,
                    context=self._format_feedback_context(last_result),
                )

            # 其他硬性校验未通过：根据问题类型选择润色策略
            # 连续润色格式失败：降级为全文重写
            if getattr(self, '_polish_format_fail_count', 0) >= 2:
                self._emit({"status": "info", "message": f"连续{self._polish_format_fail_count}次润色格式不匹配，降级为全文重写"})
                self._polish_format_fail_count = 0
                self._rewrite_count += 1
                return MWRTask(
                    action="write",
                    chapter_num=self._current_chapter,
                    focus_issues=last_result.issues,
                    context=self._format_feedback_context(last_result),
                )

            if self._polish_count < self.max_polish_rounds:
                issue_type = self._classify_issues(last_result.issues)
                self._polish_count += 1

                if issue_type == "global":
                    return MWRTask(
                        action="polish_fulltext",
                        chapter_num=self._current_chapter,
                        focus_issues=last_result.issues,
                        context=self._format_feedback_context(last_result),
                    )
                else:
                    return MWRTask(
                        action="polish",
                        chapter_num=self._current_chapter,
                        focus_issues=last_result.issues,
                        context=self._format_feedback_context(last_result),
                    )

            # 润色次数用尽且硬性校验仍未通过
            self._emit({"status": "chapter_needs_review", "chapter": self._current_chapter})
            return MWRTask(action="accept_current", chapter_num=self._current_chapter)

        # 硬性校验通过但分数不够，尝试润色提升
        if last_result and last_result.all_required_passed and self._polish_count < self.max_polish_rounds:
            # 即使 all_required_passed，低分(<=4)也应该重写而非润色
            if last_result.score <= 4.0 and self._rewrite_count < 2:
                self._rewrite_count += 1
                self._emit({"status": "info", "message":
                    f"评分{last_result.score:.1f}过低，跳过润色直接重写"})
                return MWRTask(
                    action="write",
                    chapter_num=self._current_chapter,
                    focus_issues=last_result.issues,
                    context=self._format_feedback_context(last_result),
                )
            # 连续无效润色检测
            if self._ineffective_polish_count >= 2:
                self._emit({"status": "info", "message": f"连续{self._ineffective_polish_count}次无效润色，接受当前版本"})
                return MWRTask(action="accept_current", chapter_num=self._current_chapter)

            issue_type = self._classify_issues(last_result.issues)
            self._polish_count += 1

            if issue_type == "global":
                return MWRTask(
                    action="polish_fulltext",
                    chapter_num=self._current_chapter,
                    focus_issues=last_result.issues,
                    context=self._format_feedback_context(last_result),
                )
            else:
                return MWRTask(
                    action="polish",
                    chapter_num=self._current_chapter,
                    focus_issues=last_result.issues,
                    context=self._format_feedback_context(last_result),
                )

        # 润色用尽或分数不够且无法继续提升
        return MWRTask(action="accept_current", chapter_num=self._current_chapter)

    async def writer_execute(self, task: MWRTask) -> Draft:
        """Writer：写一章或润色一章。"""
        ch = task.chapter_num or self._current_chapter

        if task.action == "accept_current":
            # 润色用尽，接受当前内容，不再重写
            content = self._read_chapter(ch)
            return Draft(content=content or "", chapter_num=ch, metadata={"action": "accept"})
        elif task.action == "polish_fulltext":
            return await self._polish_chapter_fulltext(ch, task)
        elif task.action == "polish":
            return await self._polish_chapter(ch, task)
        else:
            return await self._write_chapter(ch, task)

    def _build_write_context(self, ch: int, outline: str, task: MWRTask) -> str:
        """构建写作上下文（体裁声明 + 大纲 + 细纲 + 记忆 + 前文 + 体裁注入 + 反馈）。"""
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
            context_parts.append(f"【最近章节全文 — 必须自然衔接】\n{recent}")

        # 体裁注入：InkOS 规范 + Anti-AI 规范 + 爽点结构 + Strand 节奏
        genre_injection = self.genre_adapter.get_writer_injection(stage="writing")
        if genre_injection:
            context_parts.append(genre_injection)

        # 上一轮审查反馈（重写时需要参考）
        if task.context:
            context_parts.append(f"【上一轮审查反馈 — 重写时必须解决这些问题】\n{task.context}")

        return "\n\n".join(context_parts)

    def _build_polish_context(self, ch: int, outline: str, task: MWRTask) -> str:
        """构建润色上下文（体裁声明 + 大纲 + 细纲 + 记忆 + 体裁注入 + 前文 + 审查反馈）。"""
        context_parts = []

        # ★ 体裁声明放在最前面
        genre_name = self.genre_adapter.genre_name
        if genre_name and genre_name != "通用":
            context_parts.append(f"【体裁要求 — 最高优先级，必须遵守】\n本作品体裁为「{genre_name}」。润色时必须确保内容符合{genre_name}体裁，禁止出现科幻、赛博朋克等不符元素。")

        # 大纲
        if outline:
            context_parts.append(f"【小说大纲】\n{outline}")

        # 章节细纲（润色也需要知道本章情节目标，避免偏离大纲）
        ch_outline = self._read_chapter_outline(ch)
        if ch_outline:
            context_parts.append(f"【本章细纲】\n{ch_outline}")

        # 融合记忆
        memory_block = self._read_fused_memory(ch)
        if memory_block:
            context_parts.append(memory_block)

        # 体裁注入（润色也需要遵守 InkOS 规范和 Anti-AI 规范）
        genre_injection = self.genre_adapter.get_writer_injection(stage="writing")
        if genre_injection:
            context_parts.append(genre_injection)

        # 前章上下文（润色也需要知道前文以保证衔接）
        recent = self._read_recent_chapters(3)
        if recent:
            context_parts.append(f"【最近章节 — 润色时必须保持衔接】\n{recent}")

        # 审查反馈（issues + suggestions 都要传递给 Writer）
        feedback_parts = []
        if task.focus_issues:
            feedback_parts.append("问题：\n" + "\n".join(f"- {iss}" for iss in task.focus_issues))
        if task.context:
            feedback_parts.append(task.context)
        if feedback_parts:
            context_parts.append(f"【审查反馈 — 请针对这些问题修改】\n" + "\n\n".join(feedback_parts))

        return "\n\n".join(context_parts)

    async def _write_chapter(self, ch: int, task: MWRTask) -> Draft:
        """写新章节。"""
        self._emit({"status": "chapter_writing", "chapter": ch})

        # 构建上下文 — KG 为主，memory 为辅，体裁+反幻觉为增强
        outline = self._read_outline_summary()
        context_str = self._build_write_context(ch, outline, task)

        system_prompt = self.prompts["writer_writing"] + "\n\n" + context_str
        word_min = self.mode_config['word_count_min']
        word_max = self.mode_config['word_count_max']
        user_prompt = (
            f"请写第{ch}章。严格按照细纲和大纲写作，不要偏离主线。\n\n"
            f"【字数硬性要求】正文必须达到 {word_min}-{word_max} 字，不足 {word_min} 字视为不合格。"
            f"请充分展开场景描写、对话、心理活动和动作细节，确保篇幅达标。\n\n"
            f"【衔接硬性要求】\n"
            f"1. 本章开头必须与前一章结尾的场景、角色状态、物理位置自然衔接\n"
            f"2. 前章已确立的关键状态（如角色受伤、道具损毁、位置转移）不得在本章中被忽略或矛盾\n"
            f"3. 禁止凭空引入知识图谱中不存在的角色\n\n"
            f"【写作规范】\n"
            f"1. 避免与前文重复的描写模式（如反复用'指节泛白'、'嘴角扯出弧度'、'旧伤作痛'等），每章的描写方式应各不相同\n"
            f"2. 章节开头必须与前一章结尾自然衔接，不要每章都用天气/场景描写开头——延续前文场景时直接接续叙事，切换场景时才用场景描写开头\n"
            f"3. 正文中禁止出现FS编号（如FS-001、FS-002等），伏笔编号仅用于大纲和知识图谱的内部管理，小说正文不得引用\n"
            f"4. 章节开头第一行必须写：# 第{ch}章\n"
            f"5. 不要模仿前文中的省略号（……），用完整的句子和动作描写来表达停顿和情绪"
        )

        if not self.llm.has_valid_config("writer"):
            content = f"# 第{ch}章\n\n（未配置 LLM，占位内容）"
        else:
            try:
                content = await self.llm.call_strict("writer", system_prompt, user_prompt)
            except LLMError as e:
                self._emit({"status": "warning", "message": f"第{ch}章写作失败（LLM错误）: {e}"})
                return Draft(content="", chapter_num=ch, metadata={"action": "write", "llm_error": True})

        # 检查 LLM 返回是否为空或过短（包括非标准错误如 "Connection error."）
        cn_count = len(re.findall(r'[\u4e00-\u9fff]', content)) if content else 0
        if not content or not content.strip() or cn_count < 50:
            error_msg = content[:200] if content else "空响应"
            self._emit({"status": "warning", "message": f"第{ch}章写作失败（可能LLM连接异常）: {error_msg}"})
            return Draft(content="", chapter_num=ch, metadata={"action": "write", "llm_error": True})

        # 清洗LLM输出中的FS编号（防止LLM忽略禁止指令）
        content = self._clean_fs_ids(content)

        # 多层后处理流水线（省略号+对话标签+AI短语+句长波动）
        content = self._post_process(content)

        # 去除完全重复的段落（LLM偶发整段复制粘贴）
        content = self._deduplicate_paragraphs(content)

        # 程序化添加章节标题（避免 LLM 遗漏导致 MWR 卡死）
        if not re.search(rf'第\s*{ch}\s*[章节]', content.strip()[:200]):
            content = f"# 第{ch}章\n\n{content}"

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
        """润色已有章节 — LLM输出完整章节，程序化还原非问题段落。

        核心策略：让LLM输出完整章节（解决格式失败问题），
        然后程序化将非问题段落还原为原文（解决全部重写问题）。
        """
        self._emit({"status": "chapter_polishing", "chapter": ch, "polish_round": self._polish_count})

        original = self._read_chapter(ch)
        if not original:
            return await self._write_chapter(ch, task)

        # 如果没有具体问题需要修复，直接返回原文
        if not task.focus_issues:
            return Draft(content=original, chapter_num=ch, metadata={"action": "polish", "no_changes": True})

        # 构建润色上下文
        outline = self._read_outline_summary()
        context_str = self._build_polish_context(ch, outline, task)

        system_prompt = self.prompts["writer_polish"] + "\n\n" + context_str

        # 将原文按段落分割
        paragraphs = [p for p in original.split("\n\n") if p.strip()]

        word_min = self.mode_config['word_count_min']
        word_max = self.mode_config['word_count_max']

        # 推断问题段落编号
        problem_paragraph_nums = self._infer_problem_paragraphs(paragraphs, task.focus_issues)

        # 构建带标注的原文：需修改段落标注 [需修改]，其他标注 [无需修改，禁止改动]
        numbered_original_parts = []
        for i, p in enumerate(paragraphs):
            para_num = i + 1
            if para_num in problem_paragraph_nums:
                numbered_original_parts.append(f"[P{para_num} · 需修改] {p}")
            else:
                numbered_original_parts.append(f"[P{para_num} · 无需修改，禁止改动] {p}")
        numbered_original = "\n\n".join(numbered_original_parts)

        user_prompt = (
            f"请润色第{ch}章。根据审查反馈进行针对性修改。\n\n"
            "【重要】请输出完整的修改后章节全文。\n"
            "只修改标注为'需修改'的段落，标注为'无需修改'的段落必须原样保留，一字不改。\n"
            "保持与原文相同的段落结构（相同的段落数量和顺序，不要合并或拆分段落）。\n\n"
            f"【字数要求】修改后总字数不得低于原文（{word_min}-{word_max}字）。\n\n"
            f"--- 原文（段落已编号）---\n{numbered_original}\n--- 原文结束 ---"
        )

        if not self.llm.has_valid_config("writer"):
            content = original
            polish_format_failed = True
        else:
            try:
                llm_output = await self.llm.call_strict("writer", system_prompt, user_prompt)
                # 检测LLM是否使用了旧 ===REPLACE=== 格式（兼容）
                if re.search(r'===REPLACE\s+P\d+===', llm_output):
                    self._emit({"status": "info", "message": "LLM使用了段落替换格式，使用兼容解析器"})
                    content, polish_format_failed = self._apply_paragraph_edits_v2(original, paragraphs, llm_output)
                else:
                    # LLM输出了完整章节，程序化还原非问题段落
                    content, polish_format_failed = self._apply_fulltext_with_restore(
                        original, paragraphs, llm_output, problem_paragraph_nums
                    )
            except LLMError as e:
                self._emit({"status": "warning", "message": f"第{ch}章润色失败: {e}"})
                content = original
                polish_format_failed = True

        # 清洗LLM输出中的FS编号
        content = self._clean_fs_ids(content)

        # 多层后处理流水线
        content = self._post_process(content)

        # 去除完全重复的段落（润色后也可能产生重复）
        content = self._deduplicate_paragraphs(content)

        # 程序化添加章节标题
        if not re.search(rf'第\s*{ch}\s*[章节]', content.strip()[:200]):
            content = f"# 第{ch}章\n\n{content}"

        # 内容变空/大幅缩水检测和回退
        if not content or not content.strip():
            self._emit({"status": "warning", "message": f"第{ch}章润色后内容为空，回退到原文"})
            content = original
        else:
            original_cn = len(re.findall(r'[\u4e00-\u9fff]', original))
            new_cn = len(re.findall(r'[\u4e00-\u9fff]', content))
            if new_cn < original_cn * 0.7 and original_cn > 500:
                self._emit({"status": "warning", "message": f"第{ch}章润色后字数大幅缩水({new_cn}←{original_cn})，回退到原文"})
                content = original

        # 润色差异检测：检查是否有实质修改
        if content != original:
            is_effective = self._check_polish_effectiveness(original, content)
            if not is_effective:
                self._ineffective_polish_count += 1
                if self._ineffective_polish_count >= 2:
                    self._emit({"status": "warning", "message": f"第{ch}章连续{self._ineffective_polish_count}次无效润色，跳过后续润色"})
            else:
                self._ineffective_polish_count = 0
        else:
            # 内容完全没变，视为无效润色
            polish_format_failed = True
            self._polish_format_fail_count = getattr(self, '_polish_format_fail_count', 0) + 1
            # 格式失败不浪费润色次数：退回 _polish_count
            self._polish_count = max(0, self._polish_count - 1)

        # 落盘
        self._write_atomic(self._chapter_path(ch), content)

        # 更新反幻觉追踪器
        known_names = [c.get("label", "") for c in self.kg_adapter.get_characters()]
        self.hallucination_guard.update_from_chapter(content, ch, known_names)

        # 更新数据库（唯一入口）
        self._upsert_chapter_to_db(ch, content, status="polished")

        self._emit({"status": "chapter_polished", "chapter": ch})
        return Draft(content=content, chapter_num=ch, metadata={"action": "polish", "polish_format_failed": polish_format_failed})

    async def _polish_chapter_fulltext(self, ch: int, task: MWRTask) -> Draft:
        """全文润色 — 用于全局性问题（AI痕迹、省略号过多、重复句式等）。
        LLM 输出完整章节，程序化检测情节漂移并还原。
        """
        self._emit({"status": "chapter_polishing", "chapter": ch, "polish_round": self._polish_count, "mode": "fulltext"})

        original = self._read_chapter(ch)
        if not original:
            return await self._write_chapter(ch, task)

        if not task.focus_issues:
            return Draft(content=original, chapter_num=ch, metadata={"action": "polish", "no_changes": True})

        # 构建完整润色上下文（与段落润色一致，包含大纲/KG/记忆/前文）
        outline = self._read_outline_summary()
        context_str = self._build_polish_context(ch, outline, task)

        word_min = self.mode_config['word_count_min']
        word_max = self.mode_config['word_count_max']
        original_cn = len(re.findall(r'[\u4e00-\u9fff]', original))

        system_prompt = (
            "你是修订编辑(全文润色模式)。你需要输出完整的修改后章节。\n\n"
            "🔴 铁律：\n"
            "1. 保持原有情节结构不变 — 不能删减情节、不能改变事件顺序\n"
            "2. 保持角色对话内容不变 — 可以优化表达方式，但不能改变对话含义\n"
            "3. 必须修复审查反馈中列出的所有问题\n"
            "4. 输出完整的中文小说章节全文，不要输出JSON、分析报告或英文内容\n"
            "5. 正文中禁止出现FS编号\n\n"
            "全文润色重点：\n"
            "6. 重复句式：为重复的表达提供多样化的替代表达，每章描写方式各不相同\n"
            "7. AI痕迹：消除模板化描写、万能形容词、'说道'滥用，用具体动作替代\n"
            "8. 疲劳词：替换为同义但不同的表达\n\n"
            f"9. 字数要求：修改后不少于{word_min}字，当前原文{original_cn}字，修改后字数不得低于原文\n"
        )

        user_prompt = (
            f"请全文润色第{ch}章，修复上述所有问题。\n\n"
            f"【字数要求】修改后总字数不得低于原文（{word_min}-{word_max}字）。\n\n"
            f"--- 原文 ---\n{original}\n--- 原文结束 ---"
        )

        if context_str:
            system_prompt += "\n\n" + context_str

        paragraphs = [p for p in original.split("\n\n") if p.strip()]

        if not self.llm.has_valid_config("writer"):
            content = original
            polish_format_failed = True
        else:
            try:
                llm_output = await self.llm.call_strict("writer", system_prompt, user_prompt)
                # 全文润色也用还原机制：检测情节漂移
                all_nums = set(range(1, len(paragraphs) + 1))
                content, polish_format_failed = self._apply_fulltext_with_restore(
                    original, paragraphs, llm_output, all_nums, fulltext_mode=True
                )
            except LLMError as e:
                self._emit({"status": "warning", "message": f"第{ch}章全文润色失败: {e}"})
                content = original
                polish_format_failed = True

        # 清洗
        content = self._clean_fs_ids(content)

        # 程序化替换多余省略号
        content = self._reduce_ellipsis(content)

        # 去除完全重复的段落
        content = self._deduplicate_paragraphs(content)

        # 程序化添加章节标题
        if not re.search(rf'第\s*{ch}\s*[章节]', content.strip()[:200]):
            content = f"# 第{ch}章\n\n{content}"

        # 内容变空/大幅缩水检测
        if not content or not content.strip():
            self._emit({"status": "warning", "message": f"第{ch}章全文润色后内容为空，回退到原文"})
            content = original
            polish_format_failed = True
        else:
            new_cn = len(re.findall(r'[\u4e00-\u9fff]', content))
            if new_cn < original_cn * 0.7 and original_cn > 500:
                self._emit({"status": "warning", "message": f"第{ch}章全文润色后字数大幅缩水({new_cn}←{original_cn})，回退到原文"})
                content = original
                polish_format_failed = True

        # 润色差异检测
        if content != original:
            is_effective = self._check_polish_effectiveness(original, content)
            if not is_effective:
                self._ineffective_polish_count += 1
            else:
                self._ineffective_polish_count = 0
        else:
            polish_format_failed = True

        # 落盘
        self._write_atomic(self._chapter_path(ch), content)

        # 更新反幻觉追踪器
        known_names = [c.get("label", "") for c in self.kg_adapter.get_characters()]
        self.hallucination_guard.update_from_chapter(content, ch, known_names)

        # 更新数据库
        self._upsert_chapter_to_db(ch, content, status="polished")

        self._emit({"status": "chapter_polished", "chapter": ch, "mode": "fulltext"})
        return Draft(content=content, chapter_num=ch, metadata={"action": "polish", "polish_format_failed": polish_format_failed})

    def _apply_fulltext_with_restore(self, original: str, original_paragraphs: list,
                                      llm_output: str, problem_nums: set,
                                      fulltext_mode: bool = False) -> tuple:
        """LLM输出完整章节后，程序化还原非问题段落。

        策略：
        1. 段落数匹配 → 按索引还原非问题段落（最可靠）
        2. 段落数接近 → 模糊对齐后还原
        3. 差异过大 → 接受LLM全文（LLM可能重组了段落结构）

        fulltext_mode: 全文润色模式，所有段落都是问题段落，
            但仍然检测情节漂移（相似度<0.4的段落会被还原）

        Returns: (content, format_failed)
        """
        llm_cleaned = llm_output.strip()

        if not llm_cleaned:
            return original, True

        # 分割LLM输出为段落
        llm_paragraphs = [p for p in llm_cleaned.split("\n\n") if p.strip()]

        # 清理LLM可能复制的段落编号标记 [PN · 需修改/无需修改]
        llm_paragraphs = [
            re.sub(r'^\[P\d+\s*(?:·\s*(?:需修改|无需修改|禁止改动))?\]\s*', '', p).strip()
            for p in llm_paragraphs
        ]
        llm_paragraphs = [p for p in llm_paragraphs if p]

        # 去除标题行用于对齐
        orig_paras = [p.strip() for p in original_paragraphs
                      if not re.match(r'^#\s*第\s*\d+\s*[章节]', p.strip())]
        llm_paras = [p for p in llm_paragraphs
                     if not re.match(r'^#\s*第\s*\d+\s*[章节]', p)]

        # 情况1：段落数匹配 → 按索引精确还原
        if len(llm_paras) == len(orig_paras) and len(orig_paras) > 0:
            import difflib
            restored_count = 0
            drift_count = 0
            result = []
            for i, (orig, new) in enumerate(zip(orig_paras, llm_paras)):
                para_num = i + 1
                if para_num in problem_nums and not fulltext_mode:
                    # 段落润色模式：问题段落接受LLM修改
                    result.append(new)
                elif fulltext_mode:
                    # 全文润色模式：接受修改，但检测情节漂移
                    ratio = difflib.SequenceMatcher(None, orig[:200], new[:200]).ratio()
                    if ratio < 0.4:
                        # 相似度太低，LLM可能重写了情节，还原
                        self._emit({"status": "warning", "message":
                            f"P{para_num}相似度{ratio:.0%}过低，可能情节漂移，还原为原文"})
                        result.append(orig)
                        drift_count += 1
                    else:
                        result.append(new)
                else:
                    # 非问题段落：还原为原文
                    if orig.strip() != new.strip():
                        restored_count += 1
                    result.append(orig)
            if restored_count > 0:
                self._emit({"status": "info", "message": f"已还原{restored_count}个非问题段落为原文"})
            if drift_count > 0:
                self._emit({"status": "info", "message": f"已还原{drift_count}个情节漂移段落为原文"})
            content = "\n\n".join(result)
            return content, False

        # 情况2：段落数接近（差1-3段）→ 模糊对齐后还原
        if abs(len(llm_paras) - len(orig_paras)) <= 3 and len(orig_paras) > 3:
            result = self._fuzzy_restore_paragraphs(orig_paras, llm_paras, problem_nums)
            if result is not None:
                return result, False

        # 情况3：段落数差异大或对齐失败 → 接受LLM全文
        self._emit({"status": "warning", "message":
            f"段落数不匹配(原文{len(orig_paras)}段/LLM{len(llm_paras)}段)，接受LLM全文输出"})
        return llm_cleaned, False

    def _fuzzy_restore_paragraphs(self, orig_paras: list, llm_paras: list,
                                   problem_nums: set) -> Optional[str]:
        """模糊对齐段落后还原非问题段落。返回 None 表示对齐失败。"""
        import difflib

        # 为每个LLM段落找到最佳匹配的原文段落
        llm_to_orig = {}
        used_orig = set()

        for llm_idx, llm_p in enumerate(llm_paras):
            best_ratio = 0
            best_orig_idx = -1
            for orig_idx, orig_p in enumerate(orig_paras):
                if orig_idx in used_orig:
                    continue
                ratio = difflib.SequenceMatcher(None, orig_p[:150], llm_p[:150]).ratio()
                if ratio > best_ratio:
                    best_ratio = ratio
                    best_orig_idx = orig_idx
            if best_ratio > 0.5:
                llm_to_orig[llm_idx] = best_orig_idx
                used_orig.add(best_orig_idx)

        # 对齐率检查：至少80%的段落能对齐
        alignment_rate = len(llm_to_orig) / max(len(llm_paras), len(orig_paras))
        if alignment_rate < 0.8:
            return None

        # 还原非问题段落
        result = list(llm_paras)
        restored_count = 0
        for llm_idx, orig_idx in llm_to_orig.items():
            para_num = orig_idx + 1
            if para_num not in problem_nums:
                if orig_paras[orig_idx].strip() != llm_paras[llm_idx].strip():
                    restored_count += 1
                result[llm_idx] = orig_paras[orig_idx]

        if restored_count > 0:
            self._emit({"status": "info", "message": f"模糊对齐后还原{restored_count}个非问题段落"})

        return "\n\n".join(result)

    def _apply_paragraph_edits_v2(self, original: str, paragraphs: list, llm_output: str) -> tuple:
        """解析 LLM 的段落编辑指令，程序化应用到原文。
        返回 (content, format_failed)：content 是修改后的内容，format_failed 表示格式是否完全不匹配。
        """
        result_paragraphs = list(paragraphs)  # 复制
        edits_applied = 0

        # 匹配 ===REPLACE P{N}=== ... ===END===
        for m in re.finditer(r'===REPLACE\s+P(\d+)===\s*\n(.*?)\n===END===', llm_output, re.DOTALL):
            idx = int(m.group(1)) - 1
            new_text = m.group(2).strip()
            if 0 <= idx < len(result_paragraphs):
                result_paragraphs[idx] = new_text
                edits_applied += 1

        # 匹配 ===INSERT AFTER P{N}=== ... ===END===
        insert_offsets = {}  # 记录插入偏移量，避免索引漂移
        for m in re.finditer(r'===INSERT\s+AFTER\s+P(\d+)===\s*\n(.*?)\n===END===', llm_output, re.DOTALL):
            idx = int(m.group(1)) - 1
            new_text = m.group(2).strip()
            if 0 <= idx < len(result_paragraphs):
                offset = insert_offsets.get(idx, 0)
                result_paragraphs.insert(idx + 1 + offset, new_text)
                insert_offsets[idx] = offset + 1
                edits_applied += 1

        # Fallback 1: 如果标准格式未匹配到任何编辑，尝试宽松匹配
        if edits_applied == 0 and llm_output.strip():
            # 尝试匹配 "P{N}" 后跟换行和新内容的模式（LLM 可能省略 === 符号）
            for m in re.finditer(r'P(\d+)\s*[：:]\s*\n(.*?)(?=\nP\d+\s*[：:]|\Z)', llm_output, re.DOTALL):
                idx = int(m.group(1)) - 1
                new_text = m.group(2).strip()
                if 0 <= idx < len(result_paragraphs) and new_text:
                    result_paragraphs[idx] = new_text
                    edits_applied += 1

            if edits_applied > 0:
                self._emit({"status": "info", "message": f"润色格式使用了宽松匹配，成功应用{edits_applied}处修改"})

        # Fallback 2: 如果仍然没有匹配，检查 LLM 是否输出了完整章节
        format_failed = False
        if edits_applied == 0 and llm_output.strip():
            cn_chars = len(re.findall(r'[\u4e00-\u9fff]', llm_output))
            orig_cn = len(re.findall(r'[\u4e00-\u9fff]', original))
            # 如果 LLM 输出的中文字数 >= 原文的 80%，视为完整重写，直接使用
            if cn_chars >= orig_cn * 0.8:
                self._emit({"status": "warning", "message": f"润色格式不匹配，但LLM输出了完整章节（{cn_chars}字），直接使用"})
                return llm_output, False
            else:
                self._emit({"status": "warning", "message": "润色输出格式不匹配任何编辑指令，且输出过短，未应用修改"})
                format_failed = True

        return "\n\n".join(result_paragraphs), format_failed

    def _deduplicate_paragraphs(self, content: str) -> str:
        """去除连续重复的段落，或长段落（>50字）的跨段重复。"""
        paragraphs = content.split("\n\n")
        result = []
        prev_stripped = ""
        long_seen = set()
        for p in paragraphs:
            stripped = p.strip()
            if not stripped:
                result.append(p)
                prev_stripped = ""
                continue
            # 连续重复：无论长短都去除
            if stripped == prev_stripped:
                self._emit({"status": "warning", "message": f"检测到连续重复段落已去除: {stripped[:50]}..."})
                continue
            # 长段落（>50字）跨段重复
            if len(stripped) > 50 and stripped in long_seen:
                self._emit({"status": "warning", "message": f"检测到重复长段落已去除: {stripped[:50]}..."})
                continue
            if len(stripped) > 50:
                long_seen.add(stripped)
            result.append(p)
            prev_stripped = stripped
        return "\n\n".join(result)

    def _check_polish_effectiveness(self, original: str, polished: str) -> bool:
        """检查润色后内容是否与原文有实质差异。

        Returns:
            True = 有效润色（有实质修改），False = 无效润色（几乎没改）
        """
        if not original or not polished:
            return False

        # 按段落对比
        orig_paras = [p.strip() for p in original.split("\n\n") if p.strip()]
        new_paras = [p.strip() for p in polished.split("\n\n") if p.strip()]

        if not orig_paras or not new_paras:
            return False

        # 计算有差异的段落比例
        changed_count = 0
        max_len = max(len(orig_paras), len(new_paras))
        for i in range(min(len(orig_paras), len(new_paras))):
            if orig_paras[i] != new_paras[i]:
                # 进一步检查：差异是否实质（不是只换了标点或空格）
                import difflib
                ratio = difflib.SequenceMatcher(None, orig_paras[i], new_paras[i]).ratio()
                if ratio < 0.9:  # 相似度低于90%才算实质修改
                    changed_count += 1

        # 新增段落也算有效修改
        if len(new_paras) > len(orig_paras):
            changed_count += len(new_paras) - len(orig_paras)

        change_ratio = changed_count / max_len if max_len > 0 else 0
        is_effective = change_ratio >= 0.05  # 至少5%的段落有实质修改

        if not is_effective:
            self._emit({"status": "warning", "message": f"润色无效：仅{change_ratio:.0%}段落有实质修改（需≥5%），视为无效润色"})

        return is_effective

    def _infer_problem_paragraphs(self, paragraphs: list, focus_issues: list) -> set:
        """根据审查反馈推断需要修改的段落编号。

        优先解析 Reviewer 输出的 [PN] 标记（最精确），
        回退到关键词匹配（次优），
        最后默认标记首段和末段（兜底）。
        """
        problem_nums = set()
        if not focus_issues:
            return problem_nums

        # 优先解析 [PN] 标记（Reviewer 直接标注的段落编号）
        for issue in focus_issues:
            clean_issue = re.sub(r'\s*\[(?:未修复|新发现)\]', '', issue)
            for m in re.finditer(r'\[P(\d+)\]', clean_issue):
                num = int(m.group(1))
                if 1 <= num <= len(paragraphs):
                    problem_nums.add(num)

        # 如果 Reviewer 标注了段落编号，直接返回
        if problem_nums:
            return problem_nums

        # 回退：关键词匹配
        all_text = "\n".join(paragraphs)

        for issue in focus_issues:
            # 去掉 [未修复]/[新发现] 后缀
            clean_issue = re.sub(r'\s*\[(?:未修复|新发现)\]', '', issue)

            # 尝试在段落中搜索 issue 中的关键词
            for i, para in enumerate(paragraphs):
                # 提取 issue 中的中文关键词（2-6字）
                keywords = re.findall(r'[\u4e00-\u9fff]{2,6}', clean_issue)
                for kw in keywords:
                    if kw in para and len(kw) >= 2:
                        problem_nums.add(i + 1)
                        break

        # 如果没有定位到任何段落，默认标记首段和末段（衔接+钩子问题最常见）
        if not problem_nums and len(paragraphs) > 0:
            problem_nums.add(1)  # 首段（衔接问题）
            if len(paragraphs) > 1:
                problem_nums.add(len(paragraphs))  # 末段（钩子问题）
                problem_nums.add(len(paragraphs) - 1)  # 倒数第二段

        return problem_nums

    async def reviewer_evaluate(self, draft: Draft) -> ReviewResult:
        """Reviewer：硬性层（KG验证 + 格式校验 + 疲劳词 + 反幻觉本地检查）+ AI 层。

        问题继承机制：区分 persistent_issues（上轮就有，必须修）和 fresh_issues（本轮新出，给1轮缓冲）。
        - all_required_passed 只看 persistent_issues
        - fresh_issues 不阻塞通过，但记录到 _previous_issues 供下轮检查

        润色格式失败时：复用上一轮评分，避免同一内容反复评分导致分数越来越低。
        """
        ch = draft.chapter_num
        content = draft.content

        # 润色格式失败：内容没变，复用上一轮评分，避免评分越来越低
        if draft.metadata.get("polish_format_failed") and self._last_valid_ai_score is not None:
            self._emit({"status": "info", "message": f"第{ch}章润色格式不匹配，内容未变，复用上次评分{self._last_valid_ai_score}"})
            # 复用上一轮的问题（内容没变，问题也不会变）
            prev_issues = list(self._previous_issues) if self._previous_issues else ["润色格式不匹配，未能修改"]
            return ReviewResult(
                score=self._last_valid_ai_score,
                issues=prev_issues,
                suggestions=[],
                all_required_passed=False,
                hallucination_warnings=[],
            )

        # 程序化修复：确保章节标题存在（避免标题缺失成为 persistent_issue 卡死 MWR）
        if content and not re.search(rf'第\s*{ch}\s*[章节]', content.strip()[:200]):
            content = f"# 第{ch}章\n\n{content}"

        # 空内容/极低中文：直接返回低分，强制 all_required_passed=false
        cn_count = len(re.findall(r'[\u4e00-\u9fff]', content)) if content else 0
        if not content or not content.strip() or cn_count < 50:
            error_msg = content[:200] if content else "空响应"
            return ReviewResult(
                score=0.0,
                issues=[f"章节内容无效（{cn_count}字）: {error_msg}"],
                all_required_passed=False,
                hallucination_warnings=[],
            )

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

        # 7. 省略号密度检查
        ellipsis_count = len(re.findall(r'……|\.\.\.\.\.\.', content))
        if ellipsis_count > 5:
            issues.append(f"省略号过多：{ellipsis_count}个（建议每章不超过5个）")

        # === AI 层 ===
        score = 0.0
        suggestions = []
        ai_suggestions = []
        is_polish_action = draft.metadata.get("action") == "polish"

        if self.llm.has_valid_config("reviewer"):
            # 内容过少时跳过AI评审，直接给0分，避免浪费token和复用历史高分
            if word_count < 100:
                score = 0.0
                issues.append(f"内容过少({word_count}字)，跳过AI评审")
            else:
                score, ai_issues, ai_suggestions = await self._ai_review(ch, content)
                # 解析失败时复用上次有效评分，避免评分突降导致无效润色
                if "AI 评审解析失败" in ai_issues and self._last_valid_ai_score is not None:
                    score = self._last_valid_ai_score
                    ai_issues = [f"AI评审解析失败，复用上次评分{score}"]
                elif "AI 评审解析失败" not in ai_issues:
                    # 润色后评分波动保护：如果润色改了内容但AI给了更低分，取较高分
                    # 避免AI随机性导致润色反而分数下降
                    if is_polish_action and self._last_valid_ai_score is not None:
                        if score < self._last_valid_ai_score:
                            self._emit({"status": "info", "message":
                                f"润色后AI评分{score:.1f}低于上次{self._last_valid_ai_score:.1f}，取较高分"})
                            score = self._last_valid_ai_score
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

        # all_required_passed 只看 persistent_issues 中的非全局问题 + 硬性底线
        # 全局性 persistent_issues（省略号/AI痕迹等）不阻塞通过：
        #   - 这些问题可能已超出 LLM 修复能力
        #   - 段落润色修不了全局问题，全文润色也未必能修
        #   - 不应因一个顽固全局问题耗尽所有润色次数
        blocking_persistent = [
            iss for iss in persistent_issues
            if not any(kw in iss for kw in self._GLOBAL_ISSUE_KEYWORDS)
        ]
        has_persistent_blockers = len(blocking_persistent) > 0

        # all_required_passed 只看 persistent_issues + 硬性底线
        all_required_passed = (
            not has_persistent_blockers
            and len(hallucination_warnings) == 0
            and word_count >= 1000
            and format_result.get("passed", True)
        )

        # 评分调整：AI评分已包含问题惩罚，不再对persistent_issues额外扣分
        # （之前额外扣0.5分/个导致双重惩罚，分数越润越低形成负向螺旋）
        # persistent_issues 只影响 all_required_passed，不影响分数

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

        user_prompt = f"请审校第{ch}章：\n\n{content}"

        try:
            resp = await self.llm.call_strict("reviewer", system_prompt, user_prompt)
            data = extract_json_from_response(resp)
            if data:
                return float(data.get("score", 5.0)), data.get("issues", []), data.get("suggestions", [])
        except LLMError as e:
            self._emit({"status": "warning", "message": f"AI 评审 LLM 调用失败: {e}"})
        except Exception as e:
            self._emit({"status": "warning", "message": f"AI 评审解析异常: {e}"})
        return 5.0, ["AI 评审解析失败"], []

    def manager_final_decision(self) -> FinalDecision:
        writing_state = self.state.data.get("writing", {})
        rounds = writing_state.get("rounds", [])
        if rounds:
            last = rounds[-1]
            if last.get("score", 0) >= self.score_threshold:
                return FinalDecision(accepted=True, reason=f"评分{last.get('score', 0):.1f}达到阈值{self.score_threshold}，接受当前章节")
        return FinalDecision(accepted=False, reason="章节质量不达标，需人工审核")

    # ---- 辅助 ----

    def _next_unwritten_chapter(self) -> int:
        """找到下一个未写的章节。"""
        completed = self.state.data.get("writing", {}).get("completed_chapters", [])
        for ch in range(1, self.total_chapters + 1):
            if ch not in completed and not os.path.isfile(self._chapter_path(ch)):
                return ch
        return self.total_chapters + 1

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

    def _upsert_chapter_to_db(self, chapter_num: int, content: str, status: str = "drafted", score: float = 0.0):
        """将章节信息写入 SQLite 数据库（唯一入口）。

        status 流转：drafted → polished → completed
        - drafted: 首次写入（_write_chapter）
        - polished: 润色后（_polish_chapter）
        - completed: MWR循环结束后（write_chapter 最终同步）
        """
        try:
            db = ProjectDB(self.project_name)
            title = extract_chapter_title(content)
            # 如果从内容提取到有效标题，直接使用（内容是最新的）
            if title.strip() and title.strip() != "第N章":
                title = f"第{chapter_num}章 {title}"
            else:
                # 兜底：从大纲生成的标题映射中获取标题
                title = f"第{chapter_num}章"
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
            summary = content[:100].replace("\n", " ").strip()
            word_count = len(re.findall(r'[\u4e00-\u9fff]', content))
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
        self._ineffective_polish_count = 0  # 每章重置无效润色计数
        result = await self.run_mwr_cycle(
            max_rounds=self.mode_config["max_rounds_writing"],
            score_threshold=self.score_threshold,
        )
        self.state.writing_complete_chapter(chapter_num)

        # AI 驱动的 KG 摄取（替代旧的简单 add_chapter_node）
        content = self._read_chapter(chapter_num)
        try:
            if content:
                await self.kg_adapter.ai_ingest_chapter(
                    chapter_num, content,
                    llm_client=self.llm,
                    emit=self._emit,
                )
                # 更新反幻觉追踪器的记忆
                self.hallucination_guard.update_memory(content, chapter_num)
        except Exception as e:
            self._emit({"status": "warning", "message": f"第{chapter_num}章KG摄取失败: {e}"})

        # 最终同步章节到数据库（确保 status 和 score 正确，必须执行）
        try:
            self._upsert_chapter_to_db(chapter_num, content or "",
                                        status="completed", score=result.score)
        except Exception as e:
            self._emit({"status": "warning", "message": f"第{chapter_num}章同步completed状态失败: {e}"})

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
        try:
            return await self.llm.call_strict("chat", system_prompt, message)
        except LLMError as e:
            return f"[对话服务暂时不可用: {e}]"
