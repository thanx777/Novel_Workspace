"""反幻觉适配器 — 将旧版 HallucinationGuard 四个子模块整合到新引擎。

四个子模块：
1. CharacterTracker — 角色状态追踪
2. PlotThreadTracker — 情节线索追踪
3. ConsistencyChecker — 跨章节一致性交叉验证
4. FormatValidator — 章节格式与内容校验

从 hallucination_guard.py 迁移，与新引擎 KG 互补。
"""

import re
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass, field


# ============================================
# 1. CharacterTracker — 角色状态追踪
# ============================================

@dataclass
class CharacterState:
    """单个角色的当前状态"""
    name: str = ""
    aliases: List[str] = field(default_factory=list)
    appearance: str = ""
    location: str = ""
    status: str = ""
    relationships: Dict[str, str] = field(default_factory=dict)
    last_chapter: int = 0
    notes: str = ""


class CharacterTracker:
    """从文本中提取并维护角色状态。与 KG 角色节点互补：KG 存结构化数据，Tracker 存运行时状态。"""

    def __init__(self):
        self.characters: Dict[str, CharacterState] = {}

    def parse_memory(self, memory_text: str) -> None:
        if not memory_text:
            return
        lines = memory_text.split("\n")
        current_char = None
        for line in lines:
            line = line.strip()
            if not line:
                continue
            char_match = re.match(
                r'^[-*•]*\s*([\u4e00-\u9fff\w]{1,6}(?:\s*[（(][^)）]+[)）])?)\s*[：:]\s*(.+)',
                line
            )
            if char_match:
                raw_name = char_match.group(1).strip()
                desc = char_match.group(2).strip()
                name = re.sub(r'[（(][^)）]*[)）]', '', raw_name).strip()
                aliases = re.findall(r'[（(]([^)）]+)[)）]', raw_name)
                if name not in self.characters:
                    self.characters[name] = CharacterState(name=name)
                char = self.characters[name]
                if aliases:
                    char.aliases = list(set(char.aliases + aliases))
                char.notes = desc
                current_char = name
                self._parse_description(char, desc)
            elif current_char and line.startswith(("-", "•", "*")):
                sub = re.sub(r'^[-•*\s]+', '', line)
                char = self.characters.get(current_char)
                if char:
                    char.notes += "; " + sub

    def _parse_description(self, char: CharacterState, desc: str) -> None:
        loc_match = re.search(r'(?:在|位于|身处)([\u4e00-\u9fff\w]{2,10}(?:城|镇|村|山|宫|殿|府|界|域)?)', desc)
        if loc_match:
            char.location = loc_match.group(1)
        rel_matches = re.findall(r'([\u4e00-\u9fff\w]{1,6})的(\w+)', desc)
        for target, rel in rel_matches:
            if target != char.name:
                char.relationships[target] = rel

    def get_context_block(self, chapter_num: int) -> str:
        lines = ["【角色状态速查】"]
        for name, char in self.characters.items():
            if char.last_chapter > 0 and chapter_num - char.last_chapter > 10:
                continue
            loc = f"，在{char.location}" if char.location else ""
            status = f" — {char.status}" if char.status else ""
            lines.append(f"- {name}{status}{loc}")
        return "\n".join(lines) if len(lines) > 1 else ""

    def merge_memory_update(self, memory_text: str, chapter_num: int) -> None:
        self.parse_memory(memory_text)
        for char in self.characters.values():
            if char.name in memory_text:
                char.last_chapter = max(char.last_chapter, chapter_num)

    def update_from_chapter(self, chapter_text: str, chapter_num: int, known_names: List[str] = None) -> None:
        """从章节内容更新角色状态。"""
        for name in (known_names or []):
            if name in chapter_text:
                if name not in self.characters:
                    self.characters[name] = CharacterState(name=name)
                self.characters[name].last_chapter = chapter_num


# ============================================
# 2. PlotThreadTracker — 情节线索追踪
# ============================================

@dataclass
class PlotThread:
    """单条情节线索"""
    name: str = ""
    type: str = ""
    status: str = "open"
    introduced_chapter: int = 0
    resolved_chapter: int = 0
    description: str = ""


class PlotThreadTracker:
    """追踪开放的情节线和伏笔。与 KG 伏笔节点互补。"""

    def __init__(self):
        self.threads: Dict[str, PlotThread] = {}
        self._next_id = 0

    def add_thread(self, name: str, thread_type: str, description: str, chapter: int) -> str:
        tid = f"thread_{self._next_id}"
        self._next_id += 1
        self.threads[tid] = PlotThread(
            name=name, type=thread_type, description=description,
            introduced_chapter=chapter
        )
        return tid

    def resolve_thread(self, tid: str, chapter: int) -> None:
        if tid in self.threads:
            self.threads[tid].status = "resolved"
            self.threads[tid].resolved_chapter = chapter

    def get_open_threads(self) -> List[PlotThread]:
        return [t for t in self.threads.values() if t.status == "open"]

    def get_context_block(self) -> str:
        open_threads = self.get_open_threads()
        if not open_threads:
            return ""
        lines = ["【待回收伏笔与未结线索】"]
        for t in open_threads:
            ch_info = f"(自第{t.introduced_chapter}章)"
            lines.append(f"- [{t.type}] {t.name}: {t.description} {ch_info}")
        return "\n".join(lines)

    def parse_from_memory(self, memory_text: str, chapter_num: int) -> None:
        if not memory_text:
            return
        patterns = [
            (r'伏笔[：:]\s*(.+)', 'foreshadowing'),
            (r'待回收[：:]\s*(.+)', 'foreshadowing'),
            (r'未解决[：:]\s*(.+)', 'conflict'),
            (r'悬念[：:]\s*(.+)', 'mystery'),
            (r'暗线[：:]\s*(.+)', 'mystery'),
        ]
        for pattern, ttype in patterns:
            for m in re.finditer(pattern, memory_text):
                desc = m.group(1).strip()[:100]
                name = desc[:20]
                self.add_thread(name, ttype, desc, chapter_num)


# ============================================
# 3. ConsistencyChecker — 跨章节一致性交叉验证
# ============================================

class ConsistencyChecker:
    """在每章生成后进行交叉验证。"""

    def __init__(self):
        self.warnings: List[str] = []

    def build_check_prompt(
        self,
        chapter_content: str,
        chapter_num: int,
        outline: str,
        character_context: str,
        prev_chapter_end: str,
    ) -> str:
        return f"""你是小说一致性检查员。检查第{chapter_num}章是否存在以下问题。只需要简短回答"通过"或指出具体问题。

【本章内容】
{chapter_content[:2000]}

【大纲要求（本章）】
{self._extract_outline_section(outline, chapter_num)[:500]}

【上一章结尾】
{prev_chapter_end[:300]}

【角色当前状态】
{character_context[:500]}

请逐项检查（每项只回答"通过"或1句话指出问题）：
1. 衔接性：本章开头能自然接上上一章结尾吗？
2. 角色一致性：人物名、性格、说话风格与前文一致吗？
3. 大纲对齐：本章内容推进了该章大纲要点吗？
4. 内部逻辑：时间线、地点、事件逻辑有矛盾吗？
5. AI痕迹：有重复句式、万能形容词、"说道"过多等问题吗？

总结：通过 / 需修改（1句话说明）"""

    def _extract_outline_section(self, outline: str, chapter_num: int) -> str:
        if not outline:
            return ""
        patterns = [
            rf'第{chapter_num}[章节]\s*[：:]*\s*(.+)',
            rf'Chapter\s*{chapter_num}\s*[：:]*\s*(.+)',
            rf'^\s*{chapter_num}[\.\)、]\s*(.+)',
        ]
        for pattern in patterns:
            m = re.search(pattern, outline, re.MULTILINE)
            if m:
                return m.group(1).strip()[:200]
        return ""

    def check_format_issues(self, chapter_text: str) -> List[str]:
        """快速本地格式检查（不需要 LLM）。"""
        issues = []
        ai_patterns = [
            (r'不可否认', 'AI常用句式'),
            (r'总而言之', 'AI常用句式'),
            (r'值得注意的是', 'AI常用句式'),
            (r'首先.*其次.*最后', 'AI三段论'),
            (r'不禁', 'AI高频副词'),
            (r'宛如', 'AI高频副词'),
        ]
        for pattern, desc in ai_patterns:
            matches = re.findall(pattern, chapter_text)
            if len(matches) > 2:
                issues.append(f"{desc}出现{len(matches)}次")
        return issues

    def check_name_consistency(self, chapter_text: str, known_names: List[str]) -> List[str]:
        """快速本地检查：已知角色名是否在文中出现（仅记录，不强制）。"""
        issues = []
        # 检查是否有相似但不同的名字（可能是错字）
        for name in known_names:
            # 简单检查：名字的一部分出现但整体不出现
            if len(name) >= 3:
                for i in range(len(name)):
                    variant = name[:i] + name[i+1:]
                    if variant in chapter_text and name not in chapter_text:
                        issues.append(f"疑似人名错字：'{variant}' 可能是 '{name}'")
                        break
        return issues


# ============================================
# 4. FormatValidator — 结构化输出校验
# ============================================

class FormatValidator:
    """校验章节文件格式和基本内容质量。"""

    MIN_WORDS_PER_CHAPTER = 1000
    MAX_WORDS_PER_CHAPTER = 6000
    IDEAL_MIN_WORDS = 3000
    IDEAL_MAX_WORDS = 5000

    @staticmethod
    def count_chinese_chars(text: str) -> int:
        return len(re.findall(r'[\u4e00-\u9fff]', text))

    @staticmethod
    def has_chapter_title(text: str, expected_num: int = None) -> Tuple[bool, str]:
        title_patterns = [
            rf'第{expected_num}[章节]' if expected_num else r'第\d+[章节]',
            r'Chapter\s*\d+',
            r'^\s*#+\s*.*',
        ]
        for pattern in title_patterns:
            if re.search(pattern, text.strip()[:100]):
                return True, ""
        return False, f"缺少章节标题（期望：第{expected_num}章）" if expected_num else "缺少章节标题"

    @staticmethod
    def validate(content: str, chapter_num: int = None) -> Tuple[bool, List[str]]:
        issues = []
        has_title, title_issue = FormatValidator.has_chapter_title(content, chapter_num)
        if not has_title:
            issues.append(title_issue)
        char_count = FormatValidator.count_chinese_chars(content)
        if char_count < FormatValidator.MIN_WORDS_PER_CHAPTER:
            issues.append(f"字数不足：{char_count}字（最少{FormatValidator.MIN_WORDS_PER_CHAPTER}字）")
        elif char_count > FormatValidator.MAX_WORDS_PER_CHAPTER:
            issues.append(f"字数超标：{char_count}字（最多{FormatValidator.MAX_WORDS_PER_CHAPTER}字）")
        elif char_count < FormatValidator.IDEAL_MIN_WORDS:
            issues.append(f"字数偏少：{char_count}字（建议{FormatValidator.IDEAL_MIN_WORDS}-{FormatValidator.IDEAL_MAX_WORDS}字）")
        if not content.strip():
            issues.append("章节内容为空")
        if re.search(r'\[TODO\]|\[待写\]|\[此处.*\]', content):
            issues.append("包含占位符，未完成")
        return len(issues) == 0, issues

    @staticmethod
    def validate_with_quality(content: str, chapter_num: int = None) -> Dict:
        passed, issues = FormatValidator.validate(content, chapter_num)
        char_count = FormatValidator.count_chinese_chars(content)
        return {
            "passed": passed,
            "issues": issues,
            "char_count": char_count,
            "paragraph_count": len([p for p in content.split("\n\n") if p.strip()]),
            "has_title": FormatValidator.has_chapter_title(content, chapter_num)[0],
            "quality_score": FormatValidator._quality_score(content, char_count),
        }

    @staticmethod
    def _quality_score(content: str, char_count: int) -> int:
        score = 50
        if FormatValidator.IDEAL_MIN_WORDS <= char_count <= FormatValidator.IDEAL_MAX_WORDS:
            score += 20
        elif char_count >= FormatValidator.MIN_WORDS_PER_CHAPTER:
            score += 10
        dialogue_count = len(re.findall(r'["""「『].+?[""」』]', content))
        if dialogue_count > 0:
            score += min(dialogue_count, 15)
        paragraphs = [p for p in content.split("\n\n") if p.strip()]
        if 3 <= len(paragraphs) <= 20:
            score += 10
        ai_traces = len(re.findall(r'(不可否认|总而言之|值得注意的是|首先.*其次.*最后)', content))
        score -= min(ai_traces * 5, 20)
        return max(0, min(100, score))


# ============================================
# 5. HallucinationGuardAdapter — 统一入口
# ============================================

class HallucinationGuardAdapter:
    """反幻觉系统统一入口。协调四个子模块，供新引擎 Reviewer 调用。"""

    def __init__(self):
        self.tracker = CharacterTracker()
        self.plot_tracker = PlotThreadTracker()
        self.consistency = ConsistencyChecker()
        self.validator = FormatValidator()

    def update_memory(self, memory_text: str, chapter_num: int) -> None:
        """从记忆更新角色和情节状态。"""
        self.tracker.merge_memory_update(memory_text, chapter_num)
        self.plot_tracker.parse_from_memory(memory_text, chapter_num)

    def update_from_chapter(self, chapter_text: str, chapter_num: int, known_names: List[str] = None) -> None:
        """从章节内容更新运行时状态。"""
        self.tracker.update_from_chapter(chapter_text, chapter_num, known_names)

    def get_writing_context(self, chapter_num: int) -> str:
        """获取写作前应注入的上下文块。"""
        parts = []
        char_ctx = self.tracker.get_context_block(chapter_num)
        if char_ctx:
            parts.append(char_ctx)
        plot_ctx = self.plot_tracker.get_context_block()
        if plot_ctx:
            parts.append(plot_ctx)
        return "\n\n".join(parts)

    def build_consistency_check_prompt(
        self,
        chapter_content: str,
        chapter_num: int,
        outline: str,
        prev_chapter_end: str,
    ) -> str:
        """构建一致性检查 prompt（供 AI Reviewer 调用）。"""
        char_ctx = self.tracker.get_context_block(chapter_num)
        return self.consistency.build_check_prompt(
            chapter_content, chapter_num, outline, char_ctx, prev_chapter_end
        )

    def validate_chapter(self, content: str, chapter_num: int = None) -> Dict:
        """校验章节格式和质量。"""
        return self.validator.validate_with_quality(content, chapter_num)

    def quick_local_check(self, chapter_text: str, known_names: List[str] = None) -> List[str]:
        """快速本地检查（不需要 LLM）。"""
        issues = []
        issues.extend(self.consistency.check_format_issues(chapter_text))
        if known_names:
            issues.extend(self.consistency.check_name_consistency(chapter_text, known_names))
        return issues

    def get_open_plot_threads(self) -> List[Dict]:
        """获取所有未解决的情节线索。"""
        return [
            {"name": t.name, "type": t.type, "description": t.description,
             "introduced_chapter": t.introduced_chapter}
            for t in self.plot_tracker.get_open_threads()
        ]
