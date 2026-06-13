"""体裁适配器 — 将 InkOS / 体裁检测 / 追读力分类学 / Anti-AI 规范统一封装，供三引擎注入 prompt。

从旧引擎 genre_data/ 和 hallucination_guard.py 迁移整合。
"""

import os
import sys

# 将 backend 根目录加入 path，以便导入 genre_data
_backend_root = os.path.join(os.path.dirname(__file__), "..", "..")
if _backend_root not in sys.path:
    sys.path.insert(0, os.path.abspath(_backend_root))

from genre_data.inkos_data import (
    INKOS_GENRES, INKOS_AUDIT_DIMENSIONS, INKOS_FATIGUE_WORDS,
    get_inkos_genre, get_fatigue_words, get_setting_terms, get_chapter_types,
    build_inkos_writer_guide, build_inkos_reviewer_guide,
)
from genre_data.detect import (
    detect_genre, build_genre_guide, get_strand_rules, get_reviewer_dimensions,
)
from genre_data.taxonomy import (
    HOOK_TYPES, COOLPOINT_PATTERNS, MICROPAYOFF_TYPES,
    HARD_INVARIANTS, STRAND_DEFINITIONS, COOLPOINT_STRUCTURE, PRESSURE_RELEASE_RATIO,
)
from genre_data.writing_guides import ANTI_AI_GUIDE, CORE_CONSTRAINTS


class GenreAdapter:
    """体裁适配器：根据项目体裁动态构建 prompt 注入片段。"""

    def __init__(self, genre_name: str = ""):
        self.genre_name = genre_name or "通用"
        self._genre_info = None

    # ---- 体裁检测 ----

    def detect_from_task(self, task_text: str) -> str:
        """从任务文本检测体裁，更新自身。"""
        info = detect_genre(task_text)
        self.genre_name = info.get("name", "通用")
        self._genre_info = info
        return self.genre_name

    @property
    def genre_info(self) -> dict:
        if self._genre_info is None:
            self._genre_info = detect_genre(self.genre_name) if self.genre_name != "通用" else {}
        return self._genre_info

    # ---- Writer 注入 ----

    def get_writer_injection(self, stage: str = "writing") -> str:
        """构建 Writer prompt 注入片段：体裁指南 + InkOS 规范 + Anti-AI 规范。"""
        parts = []

        # 1. 体裁写作指南（genre_profiles 裁决规则）
        genre_guide = build_genre_guide(self.genre_info or {}, novel_stage=stage)
        if genre_guide:
            parts.append(genre_guide)

        # 2. InkOS Writer 指南（章节类型 + 节奏 + 爽点 + 语言铁律 + 疲劳词 + 叙事指导）
        inkos_writer = build_inkos_writer_guide(self.genre_name)
        if inkos_writer:
            parts.append(inkos_writer)

        # 3. Anti-AI 写作规范
        parts.append(ANTI_AI_GUIDE)

        # 4. 核心约束（三大定律 + Hard/Soft）
        parts.append(CORE_CONSTRAINTS)

        # 5. 爽点结构（仅写作阶段）
        if stage == "writing":
            from genre_data.writing_guides import COOLPOINT_STRUCTURE as COOLPOINT_TEXT
            parts.append(COOLPOINT_TEXT)

        # 6. Strand 三线节奏（仅写作阶段）
        if stage == "writing":
            parts.append(get_strand_rules())

        return "\n\n".join(parts) if parts else ""

    # ---- Reviewer 注入 ----

    def get_reviewer_injection(self, stage: str = "writing") -> str:
        """构建 Reviewer prompt 注入片段：审查维度 + InkOS 审查指南 + Hard Invariants。"""
        parts = []

        # 1. InkOS Reviewer 指南（审计维度 + 禁忌 + 疲劳词 + 节奏规则）
        inkos_reviewer = build_inkos_reviewer_guide(self.genre_name)
        if inkos_reviewer:
            parts.append(inkos_reviewer)

        # 2. 体裁审查维度（33维 + Hard Invariants）
        reviewer_dims = get_reviewer_dimensions()
        if reviewer_dims:
            parts.append(reviewer_dims)

        # 3. 疲劳词本地检查清单
        fatigue = get_fatigue_words(self.genre_name)
        if fatigue:
            parts.append(f"【本地疲劳词检查 — 以下词汇出现≥3次即扣分】\n{'、'.join(fatigue)}")

        return "\n\n".join(parts) if parts else ""

    # ---- Manager 注入 ----

    def get_manager_injection(self, stage: str = "writing") -> str:
        """构建 Manager prompt 注入片段：节奏管理 + Strand 规则。"""
        parts = []

        if stage == "writing":
            # Strand 三线节奏管理
            parts.append(get_strand_rules())

            # 爽点类型提示
            inkos = get_inkos_genre(self.genre_name)
            sat_types = inkos.get("satisfactionTypes", [])
            if sat_types:
                parts.append(f"【本体裁爽点类型 — 派任务时参考】\n{'、'.join(sat_types)}")

            # 章节类型
            ch_types = get_chapter_types(self.genre_name)
            if ch_types:
                parts.append(f"【本体裁章节分类 — 派任务时标注】\n{' / '.join(ch_types)}")

        return "\n\n".join(parts) if parts else ""

    # ---- Outline 注入 ----

    def get_outline_injection(self) -> str:
        """构建大纲阶段注入片段：体裁风格 + 禁忌。"""
        parts = []

        inkos = get_inkos_genre(self.genre_name)
        taboos = inkos.get("taboos", [])
        if taboos:
            parts.append(f"【体裁创作禁忌 — 大纲阶段即需规避】\n" + "\n".join(f"- {t}" for t in taboos[:6]))

        pacing = inkos.get("pacingRule", "")
        if pacing:
            parts.append(f"【体裁节奏规则】{pacing}")

        sat_types = inkos.get("satisfactionTypes", [])
        if sat_types:
            parts.append(f"【体裁爽点类型 — 规划伏笔时参考】\n{'、'.join(sat_types)}")

        return "\n\n".join(parts) if parts else ""

    # ---- 疲劳词本地检查 ----

    def check_fatigue_words(self, text: str, threshold: int = 3) -> list:
        """本地检查文本中的疲劳词，返回超过阈值的词及其出现次数。
        区分"偷懒用词"（阈值3）和"核心设定词"（阈值20）。
        """
        fatigue = get_fatigue_words(self.genre_name)
        setting = get_setting_terms(self.genre_name)
        # 从疲劳词列表中移除核心设定词（避免重复检查）
        fatigue = [w for w in fatigue if w not in setting]
        results = []
        for word in fatigue:
            count = text.count(word)
            if count >= threshold:
                results.append({"word": word, "count": count, "is_setting": False})
        # 核心设定词使用更高阈值（30次），且标记为设定词
        for word in setting:
            count = text.count(word)
            if count >= 30:
                results.append({"word": word, "count": count, "is_setting": True})
        return results

    # ---- Hard Invariants 检查 ----

    def get_hard_invariants(self) -> list:
        """返回 Hard Invariants 列表。"""
        return HARD_INVARIANTS

    # ---- Strand 管理 ----

    def get_strand_definitions(self) -> dict:
        """返回 Strand 三线定义。"""
        return STRAND_DEFINITIONS

    def parse_strand_tag(self, text: str) -> str:
        """从文本中提取 ---STRAND: XXX--- 标签。"""
        import re
        m = re.search(r'---STRAND:\s*(Quest|Fire|Constellation)', text)
        return m.group(1) if m else ""

    # ---- 钩子/爽点参考 ----

    def get_hook_types_summary(self) -> str:
        """构建钩子类型摘要。"""
        lines = ["【钩子类型参考】"]
        for name, info in HOOK_TYPES.items():
            lines.append(f"  {name}（{info['id']}）：{info['description']} — 触发：{info['trigger']}")
        return "\n".join(lines)

    def get_coolpoint_summary(self) -> str:
        """构建爽点模式摘要。"""
        lines = ["【爽点模式参考】"]
        for name, info in COOLPOINT_PATTERNS.items():
            lines.append(f"  {name}（强度{info['strength']}）：{info['structure']}")
        return "\n".join(lines)
