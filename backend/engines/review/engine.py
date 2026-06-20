"""全局审校引擎 — 逐章逐维度修改，直接写回章节文件。"""

import os
import re
import difflib
import asyncio
from typing import Dict, List, Optional

from ..common.base_engine import BaseEngine
from ..common.llm_client import LLMClient, LLMError
from ..common.kg_adapter import KGAdapter
from ..common.state import EngineState
from ..common.utils import extract_chapter_title


# 全部审校维度（pro 模式使用完整列表）
_ALL_REVIEW_DIMENSIONS = [
    ("character_arc", "人物弧光", "检查主角/配角从第1章到最后一章的性格变化是否合理"),
    ("foreshadowing", "伏笔回收", "检查所有伏笔是否都有回收章节"),
    ("consistency", "跨章一致性", "检查时间线、角色状态、场景描述是否前后矛盾"),
    ("style", "风格统一", "检查文笔风格、叙事视角是否一致"),
    ("coolpoint_hook", "爽点与钩子", "检查爽点密度和章末钩子是否到位"),
    ("ai_trace", "AI痕迹", "检测重复句式、万能形容词、说道滥用"),
]


class ReviewEngine(BaseEngine):
    """全局审校引擎：逐章逐维度审校修改。"""

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
        self._current_chapter = 0
        self._dimensions_done: List[str] = []

    # ---- 取消控制 ----

    def cancel(self):
        """取消审校流程。"""
        self.cancelled = True

    # ---- 辅助方法 ----

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

    def _get_chapter_summary(self, ch_num: int) -> str:
        """获取指定章节的摘要（前300字）。"""
        content = self._read_chapter(ch_num)
        if not content:
            return ""
        return content[:300]

    def _clean_chapter_content(self, content: str) -> str:
        """清洗章节内容：移除FS编号、统一标题格式。
        注意：保留 ---PREV/CAST/THREAD/STRAND--- 等元数据标记，
        因为写作引擎读取章节文件时依赖这些标记生成下一章。
        """
        lines = content.split("\n")
        cleaned = []
        for line in lines:
            # 清除行内的FS编号（FS-XXX、FS-XXX-Variant、FS-XXX-XX）
            line = re.sub(r"\bFS-\d+(?:-\d+)?(?:-Variant)?\b", "", line)
            # 清除残留的空括号（如"（FS-003）"删除后变成"（）"）
            line = re.sub(r"[（(]\s*[）)]", "", line)
            cleaned.append(line)

        result = "\n".join(cleaned)

        # 统一章节标题格式：第X章：→ 第X章
        result = re.sub(r"^(#+\s*第\d+章)[：:]\s*", r"\1 ", result, flags=re.MULTILINE)

        # 清除连续空行（超过2个空行压缩为1个）
        result = re.sub(r"\n{3,}", "\n\n", result)

        return result.strip() + "\n"

    # ---- 公开 API ----

    async def _review_dimension_phase1(self, ch_num: int, dim_key: str,
                                       dim_name: str, dim_desc: str) -> Dict:
        """阶段1（可并行）：分析章节问题，只输出 issues + fixes 建议（JSON），不重写全文。
        返回 dict，包含 dim_key, dim_name, score, issues, fixes，或 skipped/error 标记。
        """
        try:
            # 读取当前章节全文（每个维度独立读取）
            content = self._read_chapter(ch_num)
            if not content:
                return {"dim_key": dim_key, "dim_name": dim_name, "skipped": True, "reason": "empty_content"}

            # 构建上下文
            context_parts = []
            kg_ctx = self.kg_adapter.format_character_context()
            if kg_ctx:
                context_parts.append(kg_ctx)
            fs_ctx = self.kg_adapter.format_foreshadowing_context()
            if fs_ctx:
                context_parts.append(fs_ctx)

            # 前后章摘要
            prev_summary = self._get_chapter_summary(ch_num - 1)
            next_summary = self._get_chapter_summary(ch_num + 1)
            if prev_summary:
                context_parts.append(f"【前一章摘要】\n{prev_summary}")
            if next_summary:
                context_parts.append(f"【下一章摘要】\n{next_summary}")

            # 体裁规范
            genre_injection = self.genre_adapter.get_writer_injection()
            if genre_injection:
                context_parts.append(genre_injection)

            # 反幻觉上下文
            guard_ctx = self.hallucination_guard.get_writing_context(ch_num)
            if guard_ctx:
                context_parts.append(guard_ctx)

            # 构建prompt — 只分析问题，不重写全文
            system_prompt = (
                f"你是一位专业的小说审校编辑。当前审校维度：{dim_desc}\n\n"
                f"【重要】你只需要分析问题，不要重写全文！\n\n"
                f"任务：\n"
                f"1. 基于当前维度检查章节内容，找出所有问题\n"
                f"2. 对每个问题给出具体的修改建议（指明段落位置和修改方向）\n"
                f"3. 给出当前维度的评分（0-10分）\n\n"
                f"评分标准：\n"
                f"- 9-10：该维度完美，无任何问题\n"
                f"- 7-8：该维度基本合格，有小问题但不影响阅读\n"
                f"- 5-6：该维度有较明显问题，需要修改\n"
                f"- 3-4：该维度问题严重，必须大幅修改\n"
                f"- 0-2：该维度几乎不可用\n\n"
                f"输出格式（严格 JSON）：\n"
                f'{{"score": <0-10>, "issues": ["问题1（指明段落位置）", ...], "fixes": [{{"paragraph": <段落编号>, "issue": "问题描述", "suggestion": "修改建议"}}, ...]}}\n\n'
            )

            # AI痕迹维度：注入前3章全文用于对比重复描写
            if dim_key == "ai_trace":
                prev_chapters = self._read_recent_chapters(3)
                if prev_chapters:
                    system_prompt += (
                        f"【重复描写检测规则】\n"
                        f"请对比以下前文，检测当前章节中与前文重复的描写模式，包括：\n"
                        f"- 重复的动作描写（如反复攥拳、指节泛白、死死盯着）\n"
                        f"- 重复的神态描写（如反复冷笑、嘴角扯出弧度）\n"
                        f"- 重复的身体状态描写（如反复旧伤作痛、低血糖眩晕）\n"
                        f"- 重复的比喻（如反复用'像刀'、'像冰'形容眼神）\n"
                        f"为重复描写提供多样化的替代表达，使每章的描写方式各不相同。\n\n"
                        f"【前文参考（用于对比重复）】\n{prev_chapters}\n\n"
                    )
                system_prompt += (
                    f"【章节衔接规则】\n"
                    f"章节开头必须与前一章结尾自然衔接。不要每章都用固定模式（如天气/场景描写）开头：\n"
                    f"- 如果是延续前文场景，直接接续叙事\n"
                    f"- 如果是切换场景，可以用场景描写开头\n"
                    f"- 避免每章都以'雨'或天气描写开头\n\n"
                )

            # 跨章一致性维度：注入角色设定和前一章全文
            if dim_key == "consistency":
                # 注入角色身份设定
                character_ctx = self.kg_adapter.format_character_context()
                if character_ctx:
                    system_prompt += (
                        f"【角色身份设定 — 必须严格遵守，不得矛盾】\n"
                        f"{character_ctx}\n\n"
                    )
                # 注入前一章全文作为参考（清洗FS编号）
                prev_content = self._read_chapter(ch_num - 1) if ch_num > 1 else None
                if prev_content:
                    prev_content = self._clean_fs_ids(prev_content)
                    system_prompt += (
                        f"【前一章全文 — 当前章节必须与前文一致】\n"
                        f"{prev_content}\n\n"
                        f"请对照前一章检查：\n"
                        f"- 角色身份是否矛盾（如前文说某人是分析师，本章不能说他是记者）\n"
                        f"- 时间线是否矛盾（如前文某角色被囚禁，本章不能突然自由活动）\n"
                        f"- 角色状态是否矛盾（如前文某角色受伤，本章不能突然痊愈）\n"
                        f"- 关键事实是否矛盾（如伤疤来源、人物关系等）\n\n"
                    )

            system_prompt += "\n\n".join(context_parts)

            # 将章节内容按段落编号
            paragraphs = [p for p in content.split("\n\n") if p.strip()]
            numbered_content_parts = []
            for i, p in enumerate(paragraphs):
                numbered_content_parts.append(f"[P{i+1}] {p}")
            numbered_content = "\n\n".join(numbered_content_parts)

            user_prompt = f"【第{ch_num}章原文（段落已编号）】\n{numbered_content}\n\n请基于「{dim_name}」维度分析上述章节的问题。{dim_desc}。只输出JSON格式的分析结果，不要重写全文。"

            # 调用LLM
            if not self.llm.has_valid_config("reviewer"):
                return {"dim_key": dim_key, "dim_name": dim_name, "skipped": True, "reason": "no_llm_config"}

            try:
                llm_output = await self.llm.call_strict("reviewer", system_prompt, user_prompt)
            except LLMError as e:
                return {"dim_key": dim_key, "dim_name": dim_name, "error": str(e)}

            # 解析 JSON 输出
            score, issues, fixes = self._parse_review_json(llm_output)

            return {
                "dim_key": dim_key,
                "dim_name": dim_name,
                "score": score,
                "issues": issues,
                "fixes": fixes,
                "content": content,
            }
        except Exception as e:
            return {"dim_key": dim_key, "dim_name": dim_name, "error": str(e)}

    def _parse_review_json(self, llm_output: str) -> tuple:
        """解析审校阶段1的 JSON 输出，返回 (score, issues, fixes)。"""
        import json
        try:
            # 尝试提取 JSON
            json_match = re.search(r'\{[\s\S]*\}', llm_output)
            if json_match:
                data = json.loads(json_match.group())
                score = float(data.get("score", 5.0))
                issues = data.get("issues", [])
                fixes = data.get("fixes", [])
                return score, issues, fixes
        except (json.JSONDecodeError, ValueError) as e:
            self._emit({"status": "warning", "message": f"审校JSON解析失败: {e}"})

        # fallback：尝试提取评分
        score_match = re.search(r'"?score"?\s*[:：]\s*([\d.]+)', llm_output)
        score = float(score_match.group(1)) if score_match else 5.0
        return score, ["审校结果解析失败"], []

    async def _unified_modify_phase(self, ch_num: int, content: str,
                                     all_issues: list, all_fixes: list) -> Optional[str]:
        """阶段2：合并所有维度的问题，一次性让 LLM 按段落编辑格式修改。

        Args:
            ch_num: 章节号
            content: 当前章节原文
            all_issues: 所有维度的问题列表
            all_fixes: 所有维度的修改建议列表

        Returns:
            修改后的完整章节内容，或 None（如果修改失败）
        """
        if not all_fixes:
            return content

        # 将章节内容按段落编号
        paragraphs = [p for p in content.split("\n\n") if p.strip()]
        numbered_content_parts = []
        for i, p in enumerate(paragraphs):
            numbered_content_parts.append(f"[P{i+1}] {p}")
        numbered_content = "\n\n".join(numbered_content_parts)

        # 构建修改指令
        fix_instructions = []
        for fix in all_fixes:
            if isinstance(fix, dict):
                para = fix.get("paragraph", "?")
                issue = fix.get("issue", "")
                suggestion = fix.get("suggestion", "")
                fix_instructions.append(f"- P{para}：{issue} → {suggestion}")
            elif isinstance(fix, str):
                fix_instructions.append(f"- {fix}")

        # 确定需要修改的段落编号
        problem_paragraph_nums = set()
        for fix in all_fixes:
            if isinstance(fix, dict):
                para = fix.get("paragraph")
                if para and isinstance(para, (int, str)):
                    try:
                        problem_paragraph_nums.add(int(para))
                    except (ValueError, TypeError):
                        pass

        # 构建带标注的原文
        annotated_parts = []
        for i, p in enumerate(paragraphs):
            para_num = i + 1
            if para_num in problem_paragraph_nums:
                annotated_parts.append(f"[P{para_num} · 需修改] {p}")
            else:
                annotated_parts.append(f"[P{para_num} · 无需修改，禁止改动] {p}")
        annotated_content = "\n\n".join(annotated_parts)

        system_prompt = (
            "你是修订编辑(审校阶段)。根据以下修改建议，对章节进行针对性修改。\n\n"
            "🔴 铁律：\n"
            "1. 只输出需要修改的段落，用 ===REPLACE P{N}=== 新内容 ===END=== 格式\n"
            "2. 禁止修改修改建议中未提及的段落 — 无问题的段落必须原样保留\n"
            "3. 修改后的段落必须与原文对应段落有实质差异（不能只换几个同义词）\n\n"
            "修改流程（两步法）：\n"
            "第一步：定位 — 根据修改建议，确定哪些段落存在问题\n"
            "第二步：修改 — 只对标记的段落输出 ===REPLACE=== 指令，其余段落不动\n\n"
            "规则：\n"
            "4. 保留章节标题（第X章 ...）\n"
            "5. 保留 PREV/CAST/THREAD 标注\n"
            "6. 正文中禁止出现FS编号\n"
            "7. 修改后总字数不得低于原文\n"
        )

        # 注入体裁规范
        genre_injection = self.genre_adapter.get_writer_injection()
        if genre_injection:
            system_prompt += f"\n{genre_injection}\n"

        user_prompt = (
            f"请根据以下修改建议，修改第{ch_num}章。\n\n"
            "【重要】只修改标注为'需修改'的段落，标注为'无需修改'的段落必须原样保留！\n\n"
            f"--- 修改建议 ---\n" + "\n".join(fix_instructions) + "\n--- 修改建议结束 ---\n\n"
            f"--- 原文（段落已编号）---\n{annotated_content}\n--- 原文结束 ---"
        )

        try:
            llm_output = await self.llm.call_strict("writer", system_prompt, user_prompt)
        except LLMError as e:
            self._emit({"status": "warning", "message": f"第{ch_num}章统一修改阶段LLM错误: {e}"})
            return None

        if not llm_output or not llm_output.strip():
            self._emit({"status": "warning", "message": f"第{ch_num}章统一修改阶段LLM返回空"})
            return None

        # 应用段落编辑
        new_content = self._apply_review_edits(paragraphs, llm_output)

        # 如果编辑格式不匹配，尝试直接使用 LLM 输出
        if new_content and new_content.strip() == "\n\n".join(paragraphs).strip():
            # 格式不匹配，检查 LLM 是否输出了完整章节
            cn_chars = len(re.findall(r'[\u4e00-\u9fff]', llm_output))
            orig_cn = len(re.findall(r'[\u4e00-\u9fff]', content))
            if cn_chars >= orig_cn * 0.8:
                self._emit({"status": "info", "message": f"第{ch_num}章编辑格式不匹配，使用完整输出"})
                new_content = llm_output
            else:
                self._emit({"status": "warning", "message": f"第{ch_num}章编辑格式不匹配且输出过短，保留原文"})
                return content

        return new_content

    def _apply_review_edits(self, paragraphs: list, llm_output: str) -> str:
        """解析 LLM 的段落编辑指令，程序化应用到原文。"""
        result_paragraphs = list(paragraphs)
        edits_applied = 0

        # 匹配 ===REPLACE P{N}=== ... ===END===
        for m in re.finditer(r'===REPLACE\s+P(\d+)===\s*\n(.*?)\n===END===', llm_output, re.DOTALL):
            idx = int(m.group(1)) - 1
            new_text = m.group(2).strip()
            if 0 <= idx < len(result_paragraphs):
                result_paragraphs[idx] = new_text
                edits_applied += 1

        # 匹配 ===INSERT AFTER P{N}=== ... ===END===
        insert_offsets = {}
        for m in re.finditer(r'===INSERT\s+AFTER\s+P(\d+)===\s*\n(.*?)\n===END===', llm_output, re.DOTALL):
            idx = int(m.group(1)) - 1
            new_text = m.group(2).strip()
            if 0 <= idx < len(result_paragraphs):
                offset = insert_offsets.get(idx, 0)
                result_paragraphs.insert(idx + 1 + offset, new_text)
                insert_offsets[idx] = offset + 1
                edits_applied += 1

        # Fallback: 宽松匹配
        if edits_applied == 0 and llm_output.strip():
            for m in re.finditer(r'P(\d+)\s*[：:]\s*\n(.*?)(?=\nP\d+\s*[：:]|\Z)', llm_output, re.DOTALL):
                idx = int(m.group(1)) - 1
                new_text = m.group(2).strip()
                if 0 <= idx < len(result_paragraphs) and new_text:
                    result_paragraphs[idx] = new_text
                    edits_applied += 1

            if edits_applied > 0:
                self._emit({"status": "info", "message": f"审校修改使用了宽松匹配，成功应用{edits_applied}处修改"})

        if edits_applied == 0 and llm_output.strip():
            self._emit({"status": "warning", "message": "审校修改格式不匹配任何编辑指令"})

        return "\n\n".join(result_paragraphs)

    async def run_review(self) -> Dict:
        """逐章审校修改（两阶段流程）。
        阶段1：6维度并行分析问题（只输出 issues + fixes JSON）
        阶段2：合并所有维度的问题，一次性按段落编辑格式修改
        支持断点续校：跳过已完成的章节。
        """
        chapters = self._get_all_chapters()
        results = {}

        # 断点续校：只有 review.status 为 paused 时才保留 chapters_done
        review_status = self.state.data.get("review", {}).get("status", "pending")
        if review_status == "paused":
            chapters_done = set(self.state.data.get("review", {}).get("chapters_done", []))
            self._emit({"status": "info", "message": f"断点续校，跳过已完成章节：{', '.join(str(c) for c in chapters_done) or '无'}"})
        else:
            # 全新启动，清除旧记录
            chapters_done = set()
            self.state.data.setdefault("review", {})["chapters_done"] = []
            self.state.save()

        # 设置状态为 running（在判断断点续校之后）
        self.state.review_set_status("running")
        self.state.current_stage = "review"

        was_cancelled = False

        for ch_num in sorted(chapters.keys()):
            self._current_chapter = ch_num

            # 跳过已完成的章节（断点续校）
            if ch_num in chapters_done:
                continue

            # 检查取消
            if self.cancelled:
                self._emit({"status": "review_cancelled", "chapter": ch_num, "reason": "用户取消"})
                was_cancelled = True
                break

            self._emit({
                "status": "reviewing",
                "chapter": ch_num,
                "message": f"正在审校第{ch_num}章（阶段1：并行分析问题）"
            })

            # ===== 阶段1：6维度并行分析问题 =====
            dim_tasks = []
            for dim_idx, (dim_key, dim_name, dim_desc) in enumerate(self._dimensions):
                self._current_dimension = dim_idx
                dim_tasks.append(self._review_dimension_phase1(ch_num, dim_key, dim_name, dim_desc))

            # 并行执行阶段1
            phase1_results = await asyncio.gather(*dim_tasks, return_exceptions=True)

            # 收集所有维度的问题和修改建议
            all_issues = []
            all_fixes = []
            dimension_scores = {}
            content = None

            for result in phase1_results:
                if isinstance(result, Exception):
                    self._emit({"status": "warning", "message": f"审校阶段1异常: {result}"})
                    continue

                dim_key = result["dim_key"]
                dim_name = result["dim_name"]

                if result.get("skipped"):
                    continue

                if result.get("error"):
                    self._emit({"status": "warning", "message": f"第{ch_num}章{dim_name}审校异常: {result['error']}"})
                    continue

                score = result.get("score", 5.0)
                issues = result.get("issues", [])
                fixes = result.get("fixes", [])

                dimension_scores[dim_key] = score
                all_issues.extend(issues)
                all_fixes.extend(fixes)

                if content is None:
                    content = result.get("content", "")

                self._emit({
                    "status": "review_dim_analyzed",
                    "chapter": ch_num,
                    "dimension": dim_key,
                    "dimension_name": dim_name,
                    "score": score,
                    "issue_count": len(issues),
                    "fix_count": len(fixes),
                    "message": f"第{ch_num}章{dim_name}分析完成：{len(issues)}个问题，评分{score:.1f}"
                })

            # 如果没有内容或没有问题，跳过修改
            if not content:
                self._emit({"status": "warning", "message": f"第{ch_num}章无法读取内容，跳过"})
                chapters_done.add(ch_num)
                continue

            if not all_fixes:
                self._emit({"status": "review_dim_done", "chapter": ch_num, "message": f"第{ch_num}章所有维度无问题，无需修改"})
                chapters_done.add(ch_num)
                review_data = self.state.data.setdefault("review", {})
                review_data["chapters_done"] = list(chapters_done)
                self.state.save()
                continue

            # 计算章节综合评分（各维度加权平均）
            avg_score = sum(dimension_scores.values()) / len(dimension_scores) if dimension_scores else 5.0

            self._emit({
                "status": "reviewing",
                "chapter": ch_num,
                "message": f"第{ch_num}章阶段1完成，综合评分{avg_score:.1f}，共{len(all_fixes)}处修改建议。开始阶段2：统一修改"
            })

            # ===== 阶段2：统一修改 =====
            new_content = await self._unified_modify_phase(ch_num, content, all_issues, all_fixes)

            if new_content is None or not new_content.strip():
                self._emit({"status": "warning", "message": f"第{ch_num}章统一修改失败，保留原文"})
                chapters_done.add(ch_num)
                review_data = self.state.data.setdefault("review", {})
                review_data["chapters_done"] = list(chapters_done)
                self.state.save()
                continue

            # 尝试从markdown代码块中提取内容
            if new_content and len(re.findall(r'[\u4e00-\u9fff]', new_content)) == 0:
                code_block_match = re.search(r'```(?:markdown|md|text)?\s*\n([\s\S]*?)\n```', new_content)
                if code_block_match:
                    new_content = code_block_match.group(1)

            # 内容变空/缩水检测
            if not new_content or not new_content.strip():
                self._emit({"status": "warning", "message": f"第{ch_num}章审校后内容为空，保留原文"})
                chapters_done.add(ch_num)
                continue

            original_cn = len(re.findall(r'[\u4e00-\u9fff]', content))
            new_cn = len(re.findall(r'[\u4e00-\u9fff]', new_content))
            if new_cn < original_cn * 0.5 and original_cn > 500:
                self._emit({"status": "warning", "message": f"第{ch_num}章审校后字数大幅缩水({new_cn}←{original_cn})，保留原文"})
                chapters_done.add(ch_num)
                review_data = self.state.data.setdefault("review", {})
                review_data["chapters_done"] = list(chapters_done)
                self.state.save()
                continue

            # 判断是否有实质修改并生成报告
            content_changed = new_content.strip() != content.strip()
            if content_changed:
                diff_cn = new_cn - original_cn
                sign = "+" if diff_cn >= 0 else ""
                old_lines = content.splitlines()
                new_lines = new_content.splitlines()
                diff = list(difflib.unified_diff(old_lines, new_lines, lineterm='', n=0))
                added = [l[1:].strip() for l in diff if l.startswith('+') and not l.startswith('+++')]
                removed = [l[1:].strip() for l in diff if l.startswith('-') and not l.startswith('---')]
                report_parts = [f"第{ch_num}章审校完成，已修改（{sign}{diff_cn}字），综合评分{avg_score:.1f}"]
                if removed:
                    sample_removed = removed[:3]
                    report_parts.append(f"删除{len(removed)}行，如：{'；'.join(sample_removed[:2])}")
                if added:
                    sample_added = added[:3]
                    report_parts.append(f"新增{len(added)}行，如：{'；'.join(sample_added[:2])}")
                self._emit({"status": "review_dim_done", "chapter": ch_num, "changed": True, "score": avg_score, "message": "，".join(report_parts)})
            else:
                self._emit({"status": "review_dim_done", "chapter": ch_num, "changed": False, "score": avg_score, "message": f"第{ch_num}章审校完成，无需修改，综合评分{avg_score:.1f}"})

            # 写回章节文件前，清洗元数据标记和FS编号
            new_content = self._clean_chapter_content(new_content)

            # 写回章节文件
            self._write_atomic(self._chapter_path(ch_num), new_content)

            # 同步更新数据库标题
            try:
                from project_db import ProjectDB
                db = ProjectDB(self.project_name)
                title = extract_chapter_title(new_content)
                db.upsert_chapter(chapter_index=ch_num, title=title, status="reviewed")
                db.close()
            except Exception as e:
                self._emit({"status": "warning", "message": f"第{ch_num}章DB标题同步失败: {e}"})

            # 简单硬性检查
            has_title = bool(re.match(r'#?\s*第\d+章', new_content))
            word_ratio = new_cn / original_cn if original_cn > 0 else 1.0

            results[f"ch{ch_num}"] = {
                "chapter": ch_num,
                "score": round(avg_score, 1),
                "dimension_scores": dimension_scores,
                "issue_count": len(all_issues),
                "fix_count": len(all_fixes),
                "word_ratio": round(word_ratio, 2),
                "has_title": has_title,
                "passed": has_title and word_ratio >= 0.8 and avg_score >= self.score_threshold,
            }

            chapters_done.add(ch_num)
            review_data = self.state.data.setdefault("review", {})
            review_data["chapters_done"] = list(chapters_done)
            self.state.save()

            # 章节循环结束检查取消
            if self.cancelled:
                was_cancelled = True
                break

        # 根据是否被取消设置不同状态
        if was_cancelled:
            self.state.review_set_status("paused")
        else:
            self.state.review_set_status("completed")
            self.state.current_stage = "completed"

        return {"results": results, "cancelled": was_cancelled}

    def get_status(self) -> Dict:
        review_state = self.state.data.get("review", {})
        return {
            "status": review_state.get("status", "pending"),
            "current_chapter": self._current_chapter,
            "current_dimension": self._current_dimension,
            "chapters_done": review_state.get("chapters_done", []),
        }
