"""大纲引擎 — 第一阶段：MWR 循环生成 L1/L2 大纲。"""

import os
import re
from typing import Dict, List, Optional

from ..common.base_engine import BaseEngine, MWRTask, Draft, ReviewResult, FinalDecision
from ..common.llm_client import LLMClient
from ..common.kg_adapter import KGAdapter
from ..common.state import EngineState
from ..common.utils import extract_json_from_response
from ..common.prompts import (
    MANAGER_SYSTEM, WRITER_SYSTEM_OUTLINE, REVIEWER_SYSTEM_OUTLINE,
    CHAT_SYSTEM, HALLUCINATION_CHECK_PROMPT, OUTPUT_FORMAT_CONSTRAINT,
)
from project_db import ProjectDB

# 复用现有模板和解析
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from outline_templates import (
    get_prompt, parse_markdown_to_json, validate_template,
    LAYER_NAMES, REQUIRED_FIELDS_L1, REQUIRED_FIELDS_L2,
    _parse_l2_markdown,
)

LAYER_ORDER = ["L1", "L2"]


class OutlineEngine(BaseEngine):
    """大纲引擎：MWR 循环生成 L1 → L2 大纲。"""

    def __init__(self, project_dir: str, project_name: str,
                 project_presets: Optional[Dict[str, Dict]] = None,
                 global_presets: Optional[List[Dict]] = None,
                 kg=None, yield_func=None,
                 requirements: str = "",
                 max_rounds_per_layer: Optional[int] = None,
                 score_threshold: Optional[float] = None,
                 genre: str = ""):
        super().__init__(project_dir, project_name, project_presets,
                         global_presets, kg, yield_func, genre=genre)
        self.requirements = requirements
        self.max_rounds_per_layer = max_rounds_per_layer if max_rounds_per_layer is not None else self.mode_config["max_rounds_outline"]
        self.score_threshold = score_threshold if score_threshold is not None else self.mode_config["score_threshold"]
        self._current_layer = "L1"
        self._last_feedback: List[str] = []

    # ---- 文件路径 ----

    def _outline_path(self, layer: str, ext: str = "md") -> str:
        """与旧 OutlinePipeline / v2_api 保持一致的路径。"""
        return os.path.join(self.project_dir, f"outline_{layer}.{ext}")

    # ---- 读取已有大纲 ----

    def _read_outline_md(self, layer: str) -> str:
        path = self._outline_path(layer, "md")
        if os.path.isfile(path):
            with open(path, "r", encoding="utf-8") as f:
                return f.read()
        return ""

    def _read_outline_json(self, layer: str) -> Dict:
        path = self._outline_path(layer, "json")
        if os.path.isfile(path):
            import json
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        return {}

    def _get_l1_summary(self) -> str:
        md = self._read_outline_md("L1")
        if md:
            return md[:3000]
        return ""

    def _get_l2_summary(self) -> str:
        md = self._read_outline_md("L2")
        if md:
            return md[:2000]
        return ""

    # ---- 原子写入 ----

    def _write_atomic(self, path: str, content: str):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(content)
        os.replace(tmp, path)

    # ---- MWR 实现 ----

    def manager_decide(self, round_num: int, last_result: Optional[ReviewResult] = None) -> MWRTask:
        """Manager 决定本轮任务：生成哪层大纲，是否需要重做。"""
        if last_result and not last_result.all_required_passed:
            # 上一轮有问题，在原有基础上修改（polish），而非重写
            return MWRTask(
                action="polish",
                layer=self._current_layer,
                focus_issues=last_result.issues,
                context=self._format_feedback_context(last_result),
            )

        # 否则，决定下一层
        completed = self.state.data.get("outline", {}).get("completed_layers", [])
        for layer in LAYER_ORDER:
            if layer not in completed:
                self._current_layer = layer
                return MWRTask(action="write", layer=layer)

        # 所有层都完成了
        return MWRTask(action="review", layer="all")

    async def writer_execute(self, task: MWRTask) -> Draft:
        """Writer 生成大纲。"""
        layer = task.layer or self._current_layer
        self._emit({"status": "outline_writing", "layer": layer, "round": "writer"})

        # 构建 prompt
        context = {}
        if layer == "L1":
            context["requirements"] = self.requirements
        elif layer == "L2":
            context["L1_summary"] = self._get_l1_summary()
            # 从 L1 JSON 中提取总章节数，注入 L2 prompt
            try:
                l1_json_path = os.path.join(self.project_dir, "outline_L1.json")
                if os.path.isfile(l1_json_path):
                    import json as _json
                    with open(l1_json_path, "r", encoding="utf-8") as jf:
                        l1_json = _json.load(jf)
                    tc = l1_json.get("basic", {}).get("总章节数", "")
                    if tc:
                        tc_str = str(tc).strip()
                        range_m = re.match(r"(\d+)\s*[-–—]\s*(\d+)", tc_str)
                        if range_m:
                            context["total_chapters"] = int(range_m.group(2))
                        elif tc_str.isdigit():
                            context["total_chapters"] = int(tc_str)
            except Exception:
                pass

        system_prompt = self.prompts["writer_outline"] + "\n\n" + get_prompt(layer, context)

        # ★ 体裁声明放在最前面，确保 LLM 优先遵守
        genre_name = self.genre_adapter.genre_name
        if genre_name and genre_name != "通用":
            inkos = None
            try:
                from genre_data.inkos_data import get_inkos_genre
                inkos = get_inkos_genre(genre_name)
            except Exception:
                pass
            genre_header = f"【体裁要求 — 最高优先级，必须遵守】\n本作品体裁为「{genre_name}」。大纲的世界观、场景、角色、术语必须严格符合{genre_name}体裁。"
            if inkos:
                setting_terms = inkos.get("settingTerms", [])
                if setting_terms:
                    genre_header += f"\n核心设定词：{'、'.join(setting_terms)}"
                narrative = inkos.get("narrativeGuidance", "")
                if narrative:
                    genre_header += f"\n叙事指导：{narrative}"
            genre_header += f"\n禁止使用与{genre_name}体裁不符的元素。"
            system_prompt = genre_header + "\n\n" + system_prompt

        # 注入 KG 上下文（L2）
        kg_ctx = self.kg_adapter.get_outline_layer_context(layer)
        if kg_ctx:
            system_prompt = kg_ctx + "\n\n" + system_prompt

        # 注入上一轮反馈
        if task.focus_issues:
            feedback = "\n".join(f"- {iss}" for iss in task.focus_issues)
            system_prompt += f"\n\n【上一轮评审反馈 — 请针对这些问题改进】\n{feedback}"

        # 注入体裁指南（大纲阶段：禁忌 + 节奏 + 爽点类型）
        genre_injection = self.genre_adapter.get_outline_injection()
        if genre_injection:
            system_prompt += f"\n\n{genre_injection}"

        system_prompt += OUTPUT_FORMAT_CONSTRAINT

        # polish 模式：把当前大纲内容传给 LLM，让它在原有基础上修改
        if task.action == "polish":
            current_md = self._read_outline_md(layer)
            if current_md:
                system_prompt += f"\n\n【当前大纲内容 — 请在此基础上修改，不要重写】\n{current_md[:8000]}"
            user_prompt = f"请针对评审反馈改进 {LAYER_NAMES.get(layer, layer)}，保持已有内容的优点，只修改有问题的部分。"
        else:
            user_prompt = f"请按上面的要求生成 {LAYER_NAMES.get(layer, layer)}。"

        # 调用 LLM
        if not self.llm.has_valid_config("writer"):
            self._emit({"status": "warning", "message": f"未配置 LLM，{layer} 使用占位内容"})
            md_text = self._placeholder_outline(layer)
        else:
            md_text = await self.llm.call("writer", system_prompt, user_prompt)

        # 解析 JSON
        json_data = parse_markdown_to_json(layer, md_text)

        # 落盘
        self._write_atomic(self._outline_path(layer, "md"), md_text)
        import json
        self._write_atomic(self._outline_path(layer, "json"),
                           json.dumps(json_data, ensure_ascii=False, indent=2))

        # 入知识图谱
        self._add_outline_to_graph(layer, json_data, md_text[:500])

        self._emit({"status": "outline_written", "layer": layer})
        return Draft(content=md_text, json_data=json_data, layer=layer)

    async def reviewer_evaluate(self, draft: Draft) -> ReviewResult:
        """Reviewer 双层评审：硬性校验 + AI 评分。"""
        layer = draft.layer
        json_data = draft.json_data

        # === 硬性层 ===
        # L2 校验时传入 L1 的总章节数
        tc_for_validate = 0
        if layer == "L2":
            try:
                l1_json_path = os.path.join(self.project_dir, "outline_L1.json")
                if os.path.isfile(l1_json_path):
                    import json as _json
                    with open(l1_json_path, "r", encoding="utf-8") as jf:
                        l1_json = _json.load(jf)
                    tc = l1_json.get("basic", {}).get("总章节数", "")
                    if tc:
                        tc_str = str(tc).strip()
                        range_m = re.match(r"(\d+)\s*[-–—]\s*(\d+)", tc_str)
                        if range_m:
                            tc_for_validate = int(range_m.group(2))
                        elif tc_str.isdigit():
                            tc_for_validate = int(tc_str)
            except Exception:
                pass
        valid, missing = validate_template(layer, json_data, total_chapters=tc_for_validate)
        issues = []
        if not valid:
            issues.extend([f"缺失字段: {m}" for m in missing])

        # 人名一致性（L2）
        hallucination_warnings = []
        if layer == "L2":
            names = self._extract_character_names(draft.content)
            if names:
                unknown = self.kg_adapter.validate_character_names(names)
                if unknown:
                    hallucination_warnings.extend([f"疑似幻觉角色: {n}" for n in unknown])
                    issues.extend(hallucination_warnings)

        # 伏笔 ID 匹配
        fs_ids = re.findall(r"FS-\d+", draft.content)
        if fs_ids and layer == "L2":
            unknown_fs = self.kg_adapter.validate_foreshadowing_ids(fs_ids)
            if unknown_fs:
                hallucination_warnings.extend([f"未知伏笔 ID: {fid}" for fid in unknown_fs])

        # === AI 层 ===
        score = 0.0
        suggestions = []
        if self.llm.has_valid_config("reviewer"):
            score, ai_issues, ai_suggestions = await self._ai_review(layer, draft.content, json_data)
            issues.extend(ai_issues)
            suggestions.extend(ai_suggestions)
        else:
            # 无 LLM，硬性校验通过就给 7.0
            score = 7.0 if valid else 4.0

        all_required_passed = valid and len(hallucination_warnings) == 0

        # 记录到状态
        self.state.outline_add_round(
            round_num=len(self.state.data.get("outline", {}).get("rounds", [])) + 1,
            layer=layer, score=score, issues=issues,
        )

        return ReviewResult(
            score=score, issues=issues, suggestions=suggestions,
            all_required_passed=all_required_passed,
            hallucination_warnings=hallucination_warnings,
        )

    def manager_final_decision(self) -> FinalDecision:
        """达到轮数上限时的最终决策。"""
        outline_state = self.state.data.get("outline", {})
        rounds = outline_state.get("rounds", [])
        if rounds:
            last = rounds[-1]
            if last.get("score", 0) >= 6.0:
                return FinalDecision(accepted=True, reason="评分尚可，接受当前版本")
        return FinalDecision(accepted=False, reason="达到最大轮数，大纲质量不达标，需人工审核")

    # ---- AI 评审 ----

    async def _ai_review(self, layer: str, md_text: str, json_data: Dict) -> tuple:
        """AI 评审大纲，返回 (score, issues, suggestions)。"""
        system_prompt = self.prompts["reviewer_outline"]

        # 注入 KG 上下文
        kg_ctx = self.kg_adapter.get_outline_layer_context(layer)
        if kg_ctx:
            system_prompt += f"\n\n{kg_ctx}"

        # 注入体裁审查维度（InkOS 审查指南 + 疲劳词）
        genre_reviewer = self.genre_adapter.get_reviewer_injection(stage="outline")
        if genre_reviewer:
            system_prompt += f"\n\n{genre_reviewer}"

        user_prompt = f"请评审以下大纲：\n\n{md_text[:6000]}"

        try:
            resp = await self.llm.call("reviewer", system_prompt, user_prompt)
            # 解析 JSON
            import json
            data = extract_json_from_response(resp)
            if data:
                score = float(data.get("score", 5.0))
                issues = data.get("issues", [])
                suggestions = data.get("suggestions", [])
                return score, issues, suggestions
        except Exception as e:
            self._emit({"status": "warning", "message": f"AI 评审解析失败: {e}"})

        return 5.0, ["AI 评审解析失败"], []

    # ---- 辅助方法 ----

    @staticmethod
    def _extract_json_from_response(text: str):
        """从 LLM 响应中提取 JSON，支持嵌套大括号和 markdown 代码块。"""
        import json
        # 1. 尝试从 ```json ... ``` 代码块中提取
        code_block = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', text, re.DOTALL)
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

    def _extract_character_names(self, text: str) -> List[str]:
        """从文本中提取可能的人名（简单启发式）。"""
        names = set()
        # 匹配 "姓名：XXX" 或 "姓名: XXX"
        for m in re.finditer(r"姓名\s*[：:]\s*(\S{2,6})", text):
            names.add(m.group(1))
        # 匹配 "主角：XXX" 或 "名字：XXX"
        for m in re.finditer(r"(?:主角|名字|名称)\s*[：:]\s*(\S{2,6})", text):
            name = m.group(1).strip("，。、！？")
            if len(name) >= 2:
                names.add(name)
        return list(names)

    def _placeholder_outline(self, layer: str) -> str:
        """无 LLM 时的占位内容。"""
        if layer == "L1":
            return """# L1 占位大纲

## 一、基础信息栏
1. 作品名称：示例
2. 题材类型：玄幻
3. 作品定位：测试
4. 总字数：100万字
5. 故事核心主旨：示例

## 二、世界观设定
1. 世界背景：示例
2. 核心规则：示例
3. 势力划分：示例
4. 特殊元素：示例

## 三、人物设定表
### 1. 核心主角
- 姓名：示例主角

### 2. 主要配角
- 姓名：示例配角

### 3. 反派
- 姓名：示例反派

## 四、整体剧情大纲
1. 主线剧情：示例
2. 支线剧情：示例
3. 伏笔清单：FS-001

## 五、分卷大纲
### 第1卷 开篇
- 卷核心主题：开始
- 卷定位：开篇
- 卷总章节：30
- 卷内核心冲突：起步
- 卷关键剧情节点：出场

## 六、结局规划
1. 主线结局：圆满
2. 主角最终状态：成神
3. 反派结局：被封印
"""
        elif layer == "L2":
            return """# L2 章节细纲占位

## 一、阶段划分
- 阶段1（第1-10章）：起步 — 主角登场
- 阶段2（第11-20章）：发展 — 实力提升

## 二、逐章细纲

### 第1章 开篇
- **核心目的**：主角登场
- **出场人物**：示例主角
- **章节流程**：
  1. 开场：山村少年
  2. 发展：遭遇奇遇
  3. 冲突：与恶霸对峙
  4. 转折：获得传承
  5. 收尾：踏上旅途
- **情绪/爽点**：逆袭
- **伏笔**：埋设 FS-001
- **衔接下章**：到达城镇
"""
        else:
            return ""

    def _add_outline_to_graph(self, layer: str, json_data: Dict, summary: str = ""):
        """把大纲节点入知识图谱（简单版，AI 摄取在 generate_layer 中调用）。"""
        try:
            node_id = f"outline_{layer}_root"
            self.kg_adapter.kg.add_node(
                node_id, "outline_node", LAYER_NAMES.get(layer, layer),
                summary=summary,
                attrs={"layer": layer, "json_path": self._outline_path(layer, "json")},
            )
            if layer == "L2":
                l1_id = "outline_L1_root"
                if l1_id in self.kg_adapter.kg.nodes:
                    self.kg_adapter.kg.add_edge("edge_L2_from_L1", "derived_from", node_id, l1_id)
            self.kg_adapter.kg.save()
        except Exception:
            pass  # KG 写入失败不阻塞流程

    async def _ai_ingest_outline(self, layer: str, md_text: str):
        """AI 驱动的大纲摄取到知识图谱。"""
        try:
            await self.kg_adapter.ai_ingest_outline(
                layer, md_text,
                llm_client=self.llm,
                emit=self._emit,
            )
        except Exception:
            pass  # 摄取失败不阻塞流程

    def _sync_chapters_to_db(self):
        """大纲生成完成后，更新 total_chapters 和章节标题映射（不创建章节条目）。
        章节条目在写作引擎实际写完一章后才创建，避免侧边栏显示空章节。
        """
        try:
            db = ProjectDB(self.project_name)
            chapters_found = {}  # chapter_index -> title

            # 1. 从 L2 章节细纲中提取章节标题
            l2_md = self._read_outline_md("L2")
            if l2_md:
                for m in re.finditer(r"###\s*第\s*(\d+)\s*章\s*(.+?)(?:\n|$)", l2_md):
                    idx = int(m.group(1))
                    title = m.group(2).strip().rstrip("，。、！？；：")
                    if title:
                        chapters_found[idx] = title
                for m in re.finditer(r"第\s*(\d+)\s*章\s*[：:\s]*\s*(.+?)(?:\n|$)", l2_md):
                    idx = int(m.group(1))
                    if idx not in chapters_found:
                        title = m.group(2).strip().rstrip("，。、！？；：")
                        if title:
                            chapters_found[idx] = title

            # 2. 如果 L2 没找到章节，尝试从 L1 或项目配置推断
            if not chapters_found:
                max_ch = 0
                # 优先从 L1 JSON 的 basic.总章节数 提取
                try:
                    l1_json_path = os.path.join(self.project_dir, "outline_L1.json")
                    if os.path.isfile(l1_json_path):
                        import json as _json
                        with open(l1_json_path, "r", encoding="utf-8") as jf:
                            l1_json = _json.load(jf)
                        tc = l1_json.get("basic", {}).get("总章节数", "")
                        if tc:
                            tc_str = str(tc).strip()
                            range_m = re.match(r"(\d+)\s*[-–—]\s*(\d+)", tc_str)
                            if range_m:
                                max_ch = int(range_m.group(2))
                            elif tc_str.isdigit():
                                max_ch = int(tc_str)
                except Exception:
                    pass
                # 从 L2 阶段范围推断
                if max_ch == 0 and l2_md:
                    for m in re.finditer(r"第\s*(\d+)\s*[-–—]\s*(\d+)\s*章", l2_md):
                        end_ch = int(m.group(2))
                        if end_ch > max_ch:
                            max_ch = end_ch
                # 从 L1 Markdown 推断
                if max_ch == 0:
                    l1_md = self._read_outline_md("L1")
                    if l1_md:
                        # 先尝试匹配 "总章节数：N"
                        for m in re.finditer(r"总章节数\s*[：:]*\s*(\d+)\s*章?", l1_md):
                            ch = int(m.group(1))
                            if ch > max_ch:
                                max_ch = ch
                        for m in re.finditer(r"第\s*(\d+)\s*[-–—]\s*(\d+)\s*章", l1_md):
                            end_ch = int(m.group(2))
                            if end_ch > max_ch:
                                max_ch = end_ch
                        for m in re.finditer(r"(?:总章节数|共)\s*[：:]*\s*(\d+)\s*章", l1_md):
                            ch = int(m.group(1))
                            if ch > max_ch:
                                max_ch = ch
                if max_ch > 0:
                    for i in range(1, max_ch + 1):
                        chapters_found[i] = f"第{i}章"

            # 3. 确定 total_chapters：优先从 L1 JSON，其次从 L2 阶段范围，最后用实际章节数
            total = 0
            # 3a. 优先从 L1 JSON 的 basic.总章节数 提取（支持范围格式如"120-150"取最大值）
            try:
                l1_json_path = os.path.join(self.project_dir, "outline_L1.json")
                if os.path.isfile(l1_json_path):
                    import json as _json
                    with open(l1_json_path, "r", encoding="utf-8") as jf:
                        l1_json = _json.load(jf)
                    tc = l1_json.get("basic", {}).get("总章节数", "")
                    if tc:
                        tc_str = str(tc).strip()
                        # 范围格式 "120-150" → 取最大值 150
                        range_m = re.match(r"(\d+)\s*[-–—]\s*(\d+)", tc_str)
                        if range_m:
                            total = int(range_m.group(2))
                        elif tc_str.isdigit():
                            total = int(tc_str)
            except Exception:
                pass
            # 3b. 从 L2 阶段范围推断
            if total == 0 and l2_md:
                max_ch = 0
                for m in re.finditer(r"第\s*(\d+)\s*[-–—]\s*(\d+)\s*章", l2_md):
                    end_ch = int(m.group(2))
                    if end_ch > max_ch:
                        max_ch = end_ch
                if max_ch > 0:
                    total = max_ch
            # 3c. 从 L1 Markdown 推断
            if total == 0:
                l1_md = self._read_outline_md("L1")
                if l1_md:
                    # 匹配 "总章节数：N" 或 "总章节数：N-M章"
                    for m in re.finditer(r"总章节数\s*[：:]*\s*(\d+)\s*[-–—]\s*(\d+)\s*章", l1_md):
                        total = max(total, int(m.group(2)))
                    for m in re.finditer(r"总章节数\s*[：:]*\s*(\d+)\s*章?", l1_md):
                        total = max(total, int(m.group(1)))
                    # 匹配 "N卷 / 约M章" 或 "/ M章" 格式
                    for m in re.finditer(r"/\s*约?\s*(\d+)\s*章", l1_md):
                        total = max(total, int(m.group(1)))
                    # 匹配范围格式 "N-M章"
                    for m in re.finditer(r"(\d+)\s*[-–—]\s*(\d+)\s*章", l1_md):
                        total = max(total, int(m.group(2)))
                    # 匹配 "约N章" 格式
                    for m in re.finditer(r"约\s*(\d+)\s*章", l1_md):
                        total = max(total, int(m.group(1)))
            # 3d. 兜底：用实际找到的章节数
            if total == 0 and chapters_found:
                total = max(chapters_found.keys())
            if total > 0:
                db.update_project(total_chapters=total)

            # 4. 保存章节标题映射到文件（写作引擎写完一章后用来查找标题）
            if chapters_found:
                import json as _json
                titles_path = os.path.join(self.project_dir, "chapter_titles.json")
                with open(titles_path, "w", encoding="utf-8") as f:
                    _json.dump({str(k): v for k, v in chapters_found.items()}, f, ensure_ascii=False, indent=2)

            db.close()
            self._emit({"status": "info", "message": f"📋 大纲确定共 {total} 章"})
        except Exception as e:
            self._emit({"status": "warning", "message": f"同步章节数到数据库失败: {e}"})

    # ---- 公开 API ----

    async def generate_layer(self, layer: str, requirements: str = "") -> Dict:
        """生成指定层的大纲（MWR 循环 + AI 摄取到知识图谱）。
        L2 特殊处理：先 MWR 生成阶段划分，再分批生成章节细纲。
        """
        self._current_layer = layer
        if requirements:
            self.requirements = requirements

        if layer == "L2":
            return await self._generate_l2_batched()

        result = await self.run_mwr_cycle(
            max_rounds=self.max_rounds_per_layer,
            score_threshold=self.score_threshold,
        )
        # 标记完成
        self.state.outline_complete_layer(layer)

        # AI 驱动的 KG 摄取（从大纲中提取角色/伏笔/场景/世界观）
        md_text = self._read_outline_md(layer)
        if md_text:
            await self._ai_ingest_outline(layer, md_text)

        return {
            "layer": layer,
            "score": result.score,
            "issues": result.issues,
            "all_required_passed": result.all_required_passed,
        }

    async def _generate_l2_batched(self) -> Dict:
        """L2 分批生成：直接按 L1 分卷逐卷生成章节细纲，无需额外"阶段划分"。"""
        # ---- 第1步：从 L1 提取分卷信息（JSON 优先，md 兜底） ----
        volumes = self._get_l1_volumes()
        if not volumes:
            # 尝试从 L1 markdown 中提取分卷
            volumes = self._extract_volumes_from_l1_md()

        if not volumes:
            # 尝试让 LLM 补充分卷信息
            volumes = await self._auto_fix_l1_volumes()

        if not volumes:
            self._emit({"status": "error", "layer": "L2", "message": "❌ L1 缺少分卷信息，无法生成章节细纲。请重新生成 L1 大纲，确保包含分卷（每卷必须有卷总章节）。"})
            self.state.outline_complete_layer("L2")
            return {"layer": "L2", "score": 0, "issues": ["L1 缺少分卷信息"], "all_required_passed": False}

        # ---- 第2步：按卷分批生成章节细纲 ----
        l1_summary = self._get_l1_summary()
        all_chapters_md = []
        prev_tail = ""

        for i, vol in enumerate(volumes):
            # 检查是否已被用户取消
            if self.cancelled:
                self._emit({"status": "cancelled", "layer": "L2", "message": "⏹ 用户取消，L2 生成已停止"})
                break

            vol_num = vol.get("卷号", i + 1)
            vol_name = vol.get("卷名", f"第{vol_num}卷")
            vol_chapters = vol.get("卷总章节", "")
            vol_theme = vol.get("卷核心主题", "")
            vol_conflict = vol.get("卷内核心冲突", "")
            vol_position = vol.get("卷定位", "")

            # 解析卷的章节范围
            start_ch, end_ch = self._calc_volume_chapter_range(volumes, i)
            if start_ch == 0 or end_ch == 0:
                continue

            self._emit({
                "status": "info", "layer": "L2",
                "message": f"📝 L2：生成第{vol_num}卷「{vol_name}」（第{start_ch}-{end_ch}章）[{i+1}/{len(volumes)}]..."
            })

            # 构建分批 prompt
            context = {
                "L1_summary": l1_summary,
                "phase_name": f"第{vol_num}卷 {vol_name}",
                "start_ch": start_ch,
                "end_ch": end_ch,
                "phase_goal": f"{vol_theme}；{vol_conflict}" if vol_conflict else vol_theme,
                "prev_tail": prev_tail,
            }
            prompt = get_prompt("L2_batch", context)

            # 构建系统 prompt
            system_prompt = self.prompts["writer_outline"] + "\n\n" + prompt
            genre_name = self.genre_adapter.genre_name
            if genre_name and genre_name != "通用":
                genre_header = f"【体裁要求 — 最高优先级，必须遵守】\n本作品体裁为「{genre_name}」。"
                system_prompt = genre_header + "\n\n" + system_prompt

            # 注入 KG 上下文（角色、伏笔、场景等，确保一致性）
            kg_ctx = self.kg_adapter.get_outline_layer_context("L2")
            if kg_ctx:
                system_prompt = kg_ctx + "\n\n" + system_prompt

            system_prompt += OUTPUT_FORMAT_CONSTRAINT

            user_prompt = f"请为第{vol_num}卷「{vol_name}」的第{start_ch}章到第{end_ch}章生成详细细纲。本卷定位：{vol_position}；核心冲突：{vol_conflict}。"

            # 调用 LLM
            if not self.llm.has_valid_config("writer"):
                self._emit({"status": "warning", "message": "未配置 LLM，跳过章节细纲生成"})
                break

            batch_md = await self.llm.call("writer", system_prompt, user_prompt)

            # 提取章节部分
            chapters_part = self._extract_chapters_from_batch(batch_md, start_ch, end_ch)
            if chapters_part:
                all_chapters_md.append(chapters_part)
                prev_tail = self._extract_last_chapter_tail(chapters_part)
            else:
                all_chapters_md.append(batch_md)

            # 校验本卷实际生成的章数 vs 预期章数
            actual_count = self._count_chapters_in_md(chapters_part or batch_md)
            expected_count = end_ch - start_ch + 1
            if actual_count < expected_count:
                missing = expected_count - actual_count
                self._emit({
                    "status": "warning", "layer": "L2",
                    "message": f"⚠ 第{vol_num}卷预期{expected_count}章，实际生成{actual_count}章，缺少{missing}章，正在补齐..."
                })
                # 补齐缺失章节
                last_actual_ch = start_ch + actual_count - 1
                supplement_md = await self._supplement_chapters(
                    vol_num, vol_name, last_actual_ch + 1, end_ch,
                    vol_theme, vol_conflict, chapters_part or batch_md
                )
                if supplement_md:
                    all_chapters_md[-1] = (chapters_part or batch_md) + "\n\n" + supplement_md
                    prev_tail = self._extract_last_chapter_tail(supplement_md)
                    # 二次校验补齐后的章节数
                    combined_md = all_chapters_md[-1]
                    new_count = self._count_chapters_in_md(combined_md)
                    if new_count < expected_count:
                        still_missing = expected_count - new_count
                        self._emit({
                            "status": "warning", "layer": "L2",
                            "message": f"⚠ 补齐后第{vol_num}卷仍缺{still_missing}章，将在后续流程中处理"
                        })
                    else:
                        self._emit({
                            "status": "info", "layer": "L2",
                            "message": f"✅ 第{vol_num}卷补齐成功，共{new_count}章"
                        })

            # 每卷生成后立即摄取到 KG，下一卷能看到本卷新增的实体
            vol_md = chapters_part or batch_md
            if vol_md:
                await self._ai_ingest_outline("L2", vol_md)

        # ---- 第3步：合并所有卷的章节细纲 → 最终 L2 ----
        if all_chapters_md:
            # 生成分卷概览头部
            header = self._build_l2_header(volumes)
            final_md = header + "\n\n---\n\n## 逐章细纲\n\n" + "\n\n".join(all_chapters_md)

            # 落盘
            self._write_atomic(self._outline_path("L2", "md"), final_md)
            import json
            final_json = _parse_l2_markdown(final_md)
            self._write_atomic(self._outline_path("L2", "json"),
                               json.dumps(final_json, ensure_ascii=False, indent=2))

            self._emit({"status": "info", "layer": "L2",
                         "message": f"✅ L2 章节细纲生成完成，共 {len(volumes)} 卷"})

        self.state.outline_complete_layer("L2")

        return {"layer": "L2", "score": 0, "issues": [], "all_required_passed": True}

    def _get_l1_volumes(self) -> List[Dict]:
        """从 L1 JSON 提取分卷信息。"""
        l1_json = self._read_outline_json("L1")
        if not l1_json:
            return []
        volumes = l1_json.get("volumes", [])
        if not volumes:
            return []
        # 校验：至少有一个卷有卷总章节
        valid = [v for v in volumes if v.get("卷总章节")]
        return valid if valid else []

    async def _auto_fix_l1_volumes(self) -> List[Dict]:
        """当 L1 缺少分卷信息时，尝试让 LLM 根据已有大纲补充分卷。"""
        l1_md = self._read_outline_md("L1")
        if not l1_md:
            return []

        self._emit({"status": "info", "layer": "L2", "message": "🔧 L1 缺少分卷信息，正在自动补充..."})

        if not self.llm.has_valid_config("writer"):
            return []

        system_prompt = (
            "你是一个小说大纲修复助手。用户提供的 L1 大纲缺少标准的分卷格式。"
            "请根据大纲内容，补充分卷信息。\n\n"
            "输出格式要求（严格 Markdown）：\n"
            "### 第1卷 卷名\n"
            "- 卷核心主题：...\n"
            "- 卷定位：开篇/成长/转折/高潮/收尾\n"
            "- 卷总章节：30（必须是具体数字）\n"
            "- 卷内核心冲突：...\n"
            "- 卷关键剧情节点：...\n\n"
            "注意：\n"
            "- 每卷的「卷总章节」必须是具体数字（如30），不能是范围或文字描述\n"
            "- 所有卷的章节数之和应等于总章节数\n"
            "- 只输出分卷信息，不要重复其他大纲内容"
        )
        user_prompt = f"以下是 L1 大纲，请补充分卷信息：\n\n{l1_md[:6000]}"

        try:
            resp = await self.llm.call("writer", system_prompt, user_prompt)
            if not resp or resp.startswith("[LLM_ERROR"):
                return []

            # 尝试从 LLM 响应中解析分卷
            volumes = self._extract_volumes_from_md_text(resp)

            if volumes:
                # 将补充的分卷信息追加到 L1 markdown 末尾
                l1_md_existing = self._read_outline_md("L1")
                if l1_md_existing and "### 第1卷" not in l1_md_existing:
                    separator = "\n\n---\n\n## 五、分卷大纲（自动补充）\n\n"
                    updated_md = l1_md_existing.rstrip() + separator + resp
                    self._write_atomic(self._outline_path("L1", "md"), updated_md)
                    # 更新 L1 JSON 的 volumes 字段
                    l1_json = self._read_outline_json("L1")
                    if l1_json:
                        l1_json["volumes"] = volumes
                        import json
                        self._write_atomic(self._outline_path("L1", "json"),
                                           json.dumps(l1_json, ensure_ascii=False, indent=2))
                    self._emit({"status": "info", "layer": "L2",
                                "message": f"✅ 已自动补充 {len(volumes)} 卷分卷信息"})

            return volumes
        except Exception as e:
            self._emit({"status": "warning", "layer": "L2", "message": f"自动补充分卷失败: {e}"})
            return []

    def _extract_volumes_from_md_text(self, md_text: str) -> List[Dict]:
        """从任意 markdown 文本中提取分卷信息（复用 _extract_volumes_from_l1_md 的逻辑）。"""
        volumes = []
        vol_pattern = r"###\s*第\s*(\d+)\s*卷\s*[：:]*\s*(.+?)(?=\n###|\n##|\Z)"
        for m in re.finditer(vol_pattern, md_text, re.DOTALL):
            vol_num = int(m.group(1))
            vol_content = m.group(2)
            vol_name = vol_content.split("\n", 1)[0].strip().strip("：:*").strip()
            # 提取卷总章节（容忍 **加粗** 标记，包括冒号在 ** 内部如 **卷总章节：**）
            ch_match = re.search(r"卷总章节\*{0,2}\s*[：:]*\s*\*{0,2}\s*(\d+)", vol_content)
            if not ch_match:
                ch_match = re.search(r"总章节\*{0,2}\s*[：:]*\s*\*{0,2}\s*(\d+)", vol_content)
            if not ch_match:
                ch_match = re.search(r"章节数\*{0,2}\s*[：:]*\s*\*{0,2}\s*(\d+)", vol_content)
            if not ch_match:
                continue
            ch_count = ch_match.group(1)
            theme_match = re.search(r"卷核心主题\*{0,2}\s*[：:]*\s*\*{0,2}\s*(.+?)(?:\n|$)", vol_content)
            theme = theme_match.group(1).strip().strip("*") if theme_match else ""
            conflict_match = re.search(r"卷内核心冲突\*{0,2}\s*[：:]*\s*\*{0,2}\s*(.+?)(?:\n|$)", vol_content)
            conflict = conflict_match.group(1).strip().strip("*") if conflict_match else ""
            volumes.append({
                "卷号": vol_num,
                "卷名": vol_name,
                "卷总章节": ch_count,
                "卷核心主题": theme,
                "卷内核心冲突": conflict,
            })
        return volumes

    def _extract_volumes_from_l1_md(self) -> List[Dict]:
        """从 L1 markdown 中提取分卷信息（当 L1 JSON 缺少 volumes 时的兜底）。"""
        l1_md = self._read_outline_md("L1")
        if not l1_md:
            return []
        # 匹配 "### 第N卷 卷名" 后跟 "- **卷总章节**：XX"
        volumes = []
        vol_pattern = r"###\s*第\s*(\d+)\s*卷\s*[：:]*\s*(.+?)(?=\n###|\n##|\Z)"
        for m in re.finditer(vol_pattern, l1_md, re.DOTALL):
            vol_num = int(m.group(1))
            vol_content = m.group(2)
            vol_name = vol_content.split("\n", 1)[0].strip().strip("：:*").strip()
            # 提取卷总章节（容忍 **加粗** 标记，包括冒号在 ** 内部如 **卷总章节：**）
            ch_match = re.search(r"卷总章节\*{0,2}\s*[：:]*\s*\*{0,2}\s*(\d+)", vol_content)
            if not ch_match:
                ch_match = re.search(r"总章节\*{0,2}\s*[：:]*\s*\*{0,2}\s*(\d+)", vol_content)
            if not ch_match:
                ch_match = re.search(r"章节数\*{0,2}\s*[：:]*\s*\*{0,2}\s*(\d+)", vol_content)
            if not ch_match:
                continue
            ch_count = ch_match.group(1)
            # 提取卷核心主题（容忍 **加粗** 标记，包括冒号在 ** 内部）
            theme_match = re.search(r"卷核心主题\*{0,2}\s*[：:]*\s*\*{0,2}\s*(.+?)(?:\n|$)", vol_content)
            theme = theme_match.group(1).strip().strip("*") if theme_match else ""
            # 提取卷内核心冲突（容忍 **加粗** 标记，包括冒号在 ** 内部）
            conflict_match = re.search(r"卷内核心冲突\*{0,2}\s*[：:]*\s*\*{0,2}\s*(.+?)(?:\n|$)", vol_content)
            conflict = conflict_match.group(1).strip().strip("*") if conflict_match else ""
            volumes.append({
                "卷号": vol_num,
                "卷名": vol_name,
                "卷总章节": ch_count,
                "卷核心主题": theme,
                "卷内核心冲突": conflict,
            })
        return volumes

    def _calc_volume_chapter_range(self, volumes: List[Dict], vol_index: int) -> tuple:
        """根据分卷信息计算第 vol_index 卷的起止章节号。"""
        start_ch = 1
        for i in range(vol_index):
            ch_count = self._parse_chapter_count(volumes[i].get("卷总章节", ""))
            if ch_count == 0:
                return (0, 0)
            start_ch += ch_count
        ch_count = self._parse_chapter_count(volumes[vol_index].get("卷总章节", ""))
        if ch_count == 0:
            return (0, 0)
        end_ch = start_ch + ch_count - 1
        return (start_ch, end_ch)

    @staticmethod
    def _parse_chapter_count(ch_str: str) -> int:
        """解析 "30章" 或 "30" 格式的章节数。"""
        if not ch_str:
            return 0
        m = re.search(r"(\d+)", str(ch_str))
        return int(m.group(1)) if m else 0

    def _build_l2_header(self, volumes: List[Dict]) -> str:
        """根据 L1 分卷信息生成 L2 头部（分卷概览）。"""
        lines = ["# 章节细纲\n"]
        lines.append("## 分卷概览\n")
        for vol in volumes:
            vol_num = vol.get("卷号", "?")
            vol_name = vol.get("卷名", "")
            vol_chapters = vol.get("卷总章节", "")
            vol_theme = vol.get("卷核心主题", "")
            lines.append(f"- 第{vol_num}卷「{vol_name}」：{vol_chapters} — {vol_theme}")
        return "\n".join(lines)

    def _parse_chapter_range(self, range_str: str) -> tuple:
        """解析章节范围 '第 1-30 章' → (1, 30)。"""
        m = re.search(r"第?\s*(\d+)\s*[-–—]\s*(\d+)\s*章?", range_str)
        if m:
            return int(m.group(1)), int(m.group(2))
        return 0, 0

    def _extract_chapters_from_batch(self, batch_md: str, start_ch: int, end_ch: int) -> str:
        """从分批生成结果中提取章节细纲部分。"""
        # 找到第一个 "### 第N章" 的位置
        first_match = re.search(r"###\s*第\s*\d+\s*章", batch_md)
        if first_match:
            return batch_md[first_match.start():]
        return batch_md

    def _count_chapters_in_md(self, md_text: str) -> int:
        """统计 markdown 中实际生成的章节数。"""
        if not md_text:
            return 0
        chapters = re.findall(r"###\s*第\s*\d+\s*章", md_text)
        return len(chapters)

    async def _supplement_chapters(self, vol_num: int, vol_name: str,
                                    start_ch: int, end_ch: int,
                                    vol_theme: str, vol_conflict: str,
                                    existing_md: str) -> str:
        """补齐缺失的章节细纲。"""
        l1_summary = self._get_l1_summary()
        context = {
            "L1_summary": l1_summary,
            "phase_name": f"第{vol_num}卷 {vol_name}（续）",
            "start_ch": start_ch,
            "end_ch": end_ch,
            "phase_goal": f"{vol_theme}；{vol_conflict}" if vol_conflict else vol_theme,
            "prev_tail": self._extract_last_chapter_tail(existing_md),
        }
        prompt = get_prompt("L2_batch", context)
        system_prompt = self.prompts["writer_outline"] + "\n\n" + prompt

        # 注入 KG 上下文
        kg_ctx = self.kg_adapter.get_outline_layer_context("L2")
        if kg_ctx:
            system_prompt = kg_ctx + "\n\n" + system_prompt

        system_prompt += OUTPUT_FORMAT_CONSTRAINT

        # 注入已有章节作为上下文
        last_chapters = existing_md[-3000:] if len(existing_md) > 3000 else existing_md
        user_prompt = (
            f"请为第{vol_num}卷「{vol_name}」补齐第{start_ch}章到第{end_ch}章的详细细纲。\n"
            f"以下是本卷已生成的最后部分内容，请自然衔接：\n---\n{last_chapters}\n---\n"
            f"请从第{start_ch}章开始生成，不要重复已有章节。"
        )

        if not self.llm.has_valid_config("writer"):
            return ""

        batch_md = await self.llm.call("writer", system_prompt, user_prompt)
        return self._extract_chapters_from_batch(batch_md, start_ch, end_ch)

    def _extract_last_chapter_tail(self, chapters_md: str) -> str:
        """提取最后一章的衔接信息，传给下一批。"""
        # 找最后一个 "衔接下章" 行
        matches = list(re.finditer(
            r"[-*]\s*\*{0,2}衔接下章\*{0,2}\s*[：:]\s*(.+?)(?:\n|$)",
            chapters_md
        ))
        if matches:
            return f"【上一阶段最后一章衔接】{matches[-1].group(1).strip()}"
        return ""

    async def generate_all(self, requirements: str = "") -> Dict:
        """依次生成 L1 → L2，跳过已完成的层。"""
        if requirements:
            self.requirements = requirements
        results = {}
        completed = self.state.data.get("outline", {}).get("completed_layers", [])
        outline_failed = False  # 标记大纲是否未达标
        for layer in LAYER_ORDER:
            if layer in completed:
                self._emit({"status": "info", "message": f"⏭ 跳过已完成的 {layer}"})
                continue
            self._emit({"status": "outline_layer_start", "layer": layer, "message": f"📝 开始生成 {LAYER_NAMES.get(layer, layer)}..."})
            r = await self.generate_layer(layer)
            results[layer] = r
            self._emit({"status": "outline_layer_done", "layer": layer, "score": r.get("score", 0),
                         "passed": r.get("all_required_passed", False),
                         "message": f"✅ {LAYER_NAMES.get(layer, layer)} 生成完成（评分: {r.get('score', 0):.1f}）"})
            if not r["all_required_passed"] and r["score"] < 6.0:
                # L1 不达标才暂停（L2 分批生成不依赖 MWR 评分，不应暂停）
                if layer == "L1":
                    self._emit({"status": "warning", "message": f"{layer} 质量不达标，暂停后续生成"})
                    outline_failed = True
                    break
                else:
                    self._emit({"status": "warning", "message": f"{layer} 质量未达最优，继续后续流程"})
        # 同步章节标题和总数到数据库
        self._sync_chapters_to_db()
        # 只有全部层都完成才标记为 completed，否则标记为 partial
        if outline_failed:
            self.state.outline_set_status("partial")
        else:
            self.state.outline_set_status("completed")
            self.state.current_stage = "writing"
        return results

    def get_status(self) -> Dict:
        """获取大纲引擎状态。"""
        outline_state = self.state.data.get("outline", {})
        return {
            "status": outline_state.get("status", "pending"),
            "current_layer": outline_state.get("current_layer"),
            "completed_layers": outline_state.get("completed_layers", []),
            "rounds": outline_state.get("rounds", []),
        }

    async def chat(self, message: str, layer: str = "") -> str:
        """AI 对话（带大纲上下文）。"""
        # 构建上下文
        context_parts = []
        if layer:
            md = self._read_outline_md(layer)
            if md:
                context_parts.append(f"当前{LAYER_NAMES.get(layer, layer)}：\n{md[:3000]}")

        kg_ctx = self.kg_adapter.get_outline_layer_context(layer or "L2")
        if kg_ctx:
            context_parts.append(kg_ctx)

        system_prompt = CHAT_SYSTEM
        if context_parts:
            system_prompt += "\n\n" + "\n\n".join(context_parts)

        user_prompt = message
        return await self.llm.call("chat", system_prompt, user_prompt)
