"""大纲引擎 — 第一阶段：MWR 循环生成 L1/L2/L3 大纲。"""

import os
import re
from typing import Dict, List, Optional

from ..common.base_engine import BaseEngine, MWRTask, Draft, ReviewResult, FinalDecision
from ..common.llm_client import LLMClient
from ..common.kg_adapter import KGAdapter
from ..common.state import EngineState
from ..common.prompts import (
    MANAGER_SYSTEM, WRITER_SYSTEM_OUTLINE, REVIEWER_SYSTEM_OUTLINE,
    CHAT_SYSTEM, HALLUCINATION_CHECK_PROMPT, OUTPUT_FORMAT_CONSTRAINT,
)

# 复用现有模板和解析
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from outline_templates import (
    get_prompt, parse_markdown_to_json, validate_template,
    LAYER_NAMES, REQUIRED_FIELDS_L1, REQUIRED_FIELDS_L2, REQUIRED_FIELDS_L3,
)

LAYER_ORDER = ["L1", "L2", "L3"]


class OutlineEngine(BaseEngine):
    """大纲引擎：MWR 循环生成 L1 → L2 → L3 大纲。"""

    def __init__(self, project_dir: str, project_name: str,
                 project_presets: Optional[Dict[str, Dict]] = None,
                 global_presets: Optional[List[Dict]] = None,
                 kg=None, yield_func=None,
                 requirements: str = "",
                 max_rounds_per_layer: int = 5,
                 score_threshold: float = 8.0,
                 genre: str = ""):
        super().__init__(project_dir, project_name, project_presets,
                         global_presets, kg, yield_func, genre=genre)
        self.requirements = requirements
        self.max_rounds_per_layer = max_rounds_per_layer
        self.score_threshold = score_threshold
        self._current_layer = "L1"
        self._last_feedback: List[str] = []

    # ---- 文件路径 ----

    def _outline_path(self, layer: str, ext: str = "md") -> str:
        """与旧 OutlinePipeline / v2_api 保持一致的路径。"""
        if layer in ("L1", "L2"):
            return os.path.join(self.project_dir, f"outline_{layer}.{ext}")
        # L3 根目录
        return os.path.join(self.project_dir, f"outline_L3.{ext}")

    def _l3_chapter_path(self, chapter: int, ext: str = "md") -> str:
        """与旧 OutlinePipeline / v2_api 保持一致的 L3 章节路径。"""
        d = os.path.join(self.project_dir, "outline_L3")
        os.makedirs(d, exist_ok=True)
        return os.path.join(d, f"chapter_{chapter}.{ext}")

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
            # 上一轮有问题，重做当前层
            return MWRTask(
                action="write",
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
        elif layer == "L3":
            context["L1_summary"] = self._get_l1_summary()
            context["L2_summary"] = self._get_l2_summary()

        system_prompt = WRITER_SYSTEM_OUTLINE + "\n\n" + get_prompt(layer, context)

        # 注入 KG 上下文（L2/L3）
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
        valid, missing = validate_template(layer, json_data)
        issues = []
        if not valid:
            issues.extend([f"缺失字段: {m}" for m in missing])

        # 人名一致性（L2/L3）
        hallucination_warnings = []
        if layer in ("L2", "L3"):
            names = self._extract_character_names(draft.content)
            if names:
                unknown = self.kg_adapter.validate_character_names(names)
                if unknown:
                    hallucination_warnings.extend([f"疑似幻觉角色: {n}" for n in unknown])
                    issues.extend(hallucination_warnings)

        # 伏笔 ID 匹配
        fs_ids = re.findall(r"FS-\d+", draft.content)
        if fs_ids and layer in ("L2", "L3"):
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
        system_prompt = REVIEWER_SYSTEM_OUTLINE

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
            # 尝试从响应中提取 JSON
            json_match = re.search(r'\{[^{}]*"score"[^{}]*\}', resp, re.DOTALL)
            if json_match:
                data = json.loads(json_match.group())
                score = float(data.get("score", 5.0))
                issues = data.get("issues", [])
                suggestions = data.get("suggestions", [])
                return score, issues, suggestions
        except Exception as e:
            self._emit({"status": "warning", "message": f"AI 评审解析失败: {e}"})

        return 5.0, ["AI 评审解析失败"], []

    # ---- 辅助方法 ----

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
            return """# L2 网文精简版占位大纲

## 一、基础信息
- 书名：示例
- 题材：玄幻
- 风格：爽文
- 核心爽点：升级

## 二、简略世界观
一句话

## 三、人物速览
- 主角：示例主角
- 女主/重要伙伴：示例配角
- 主要反派：示例反派

## 四、剧情总脉络
- 第一阶段（前期）：开篇
- 第二阶段（中期）：发展
- 第三阶段（后期）：结局

## 五、分阶段剧情节点
- 阶段1（第1-30章）：开篇 + 爽点：升级 + 收尾：立稳
"""
        else:
            return """# L3 单章细纲占位（第 1 章：开篇）

## 一、本章核心目的
开篇

## 二、出场人物
示例主角

## 三、章节流程
1. 开场

## 四、本章情绪/爽点
爽

## 五、伏笔
埋下 FS-001

## 六、衔接下一章内容
下一章
"""

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

    # ---- 公开 API ----

    async def generate_layer(self, layer: str, requirements: str = "") -> Dict:
        """生成指定层的大纲（MWR 循环 + AI 摄取到知识图谱）。"""
        self._current_layer = layer
        if requirements:
            self.requirements = requirements
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

    async def generate_all(self, requirements: str = "") -> Dict:
        """依次生成 L1 → L2 → L3。"""
        if requirements:
            self.requirements = requirements
        results = {}
        for layer in LAYER_ORDER:
            r = await self.generate_layer(layer)
            results[layer] = r
            if not r["all_required_passed"] and r["score"] < 6.0:
                self._emit({"status": "warning", "message": f"{layer} 质量不达标，暂停后续生成"})
                break
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
