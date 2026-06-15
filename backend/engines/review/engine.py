"""全局审校引擎 — 逐章逐维度修改，直接写回章节文件。"""

import os
import re
import difflib
from typing import Dict, List, Optional

from ..common.base_engine import BaseEngine, MWRTask, Draft, ReviewResult, FinalDecision
from ..common.llm_client import LLMClient
from ..common.kg_adapter import KGAdapter
from ..common.state import EngineState


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

    # ---- MWR 抽象方法存根（不再使用 MWR 循环，但需满足 BaseEngine 接口）----

    def manager_decide(self, round_num: int, last_result: Optional[ReviewResult] = None) -> MWRTask:
        return MWRTask(action="review")

    async def writer_execute(self, task: MWRTask) -> Draft:
        return Draft()

    async def reviewer_evaluate(self, draft: Draft) -> ReviewResult:
        return ReviewResult()

    def manager_final_decision(self) -> FinalDecision:
        return FinalDecision(accepted=True)

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

    def _write_atomic(self, path: str, content: str):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(content)
        os.replace(tmp, path)

    def _read_chapter(self, ch_num: int) -> str:
        """读取指定章节全文。"""
        path = self._chapter_path(ch_num)
        if os.path.isfile(path):
            with open(path, "r", encoding="utf-8") as f:
                return f.read()
        return ""

    def _chapter_path(self, ch_num: int) -> str:
        """获取章节文件路径。"""
        return os.path.join(self.project_dir, "chapters", f"第{ch_num}章.txt")

    def _get_chapter_summary(self, ch_num: int) -> str:
        """获取指定章节的摘要（前300字）。"""
        content = self._read_chapter(ch_num)
        if not content:
            return ""
        return content[:300]

    def _extract_chapter_title(self, content: str) -> str:
        """从内容中提取章节标题，如 '# 第一章 灵根觉醒' → '灵根觉醒'。"""
        for line in content.strip().split("\n"):
            line = line.strip()
            if not line:
                continue
            if line.startswith("---PREV:") or line.startswith("---CAST:") or line.startswith("---"):
                continue
            m = re.match(r"^#+\s*第[一二三四五六七八九十百千\d]+章\s*(.*)", line)
            if m and m.group(1).strip():
                return m.group(1).strip()
            m = re.match(r"^第[一二三四五六七八九十百千\d]+章\s+(.*)", line)
            if m and m.group(1).strip():
                return m.group(1).strip()
            m = re.match(r"^#+\s*(.+)", line)
            if m and m.group(1).strip():
                title = m.group(1).strip()
                title = re.sub(r"^第[一二三四五六七八九十百千\d]+章\s*", "", title)
                return title.strip() or "第N章"
            continue
        return "第N章"

    # ---- 公开 API ----

    async def run_review(self) -> Dict:
        """逐章逐维度审校修改。支持断点续校：跳过已完成的维度。"""
        chapters = self._get_all_chapters()
        results = {}

        # 断点续校：只有 review.status 为 paused 时才保留 dimensions_done
        review_status = self.state.data.get("review", {}).get("status", "pending")
        if review_status == "paused":
            dimensions_done = set(self.state.data.get("review", {}).get("dimensions_done", []))
            self._emit({"status": "info", "message": f"断点续校，跳过已完成维度：{', '.join(dimensions_done) or '无'}"})
        else:
            # 全新启动，清除旧记录
            dimensions_done = set()
            self.state.data.setdefault("review", {})["dimensions_done"] = []
            self.state.save()

        was_cancelled = False

        for ch_num in sorted(chapters.keys()):
            self._current_chapter = ch_num

            # 检查取消
            if self.cancelled:
                self._emit({"status": "review_cancelled", "chapter": ch_num, "reason": "用户取消"})
                was_cancelled = True
                break

            for dim_idx, (dim_key, dim_name, dim_desc) in enumerate(self._dimensions):
                self._current_dimension = dim_idx

                # 跳过已完成的维度（断点续校）
                done_key = f"ch{ch_num}_{dim_key}"
                if done_key in dimensions_done:
                    continue

                # 检查取消
                if self.cancelled:
                    self._emit({"status": "review_cancelled", "chapter": ch_num, "dimension": dim_key, "reason": "用户取消"})
                    was_cancelled = True
                    break

                # 推送进度
                self._emit({
                    "status": "reviewing",
                    "chapter": ch_num,
                    "dimension": dim_key,
                    "dimension_name": dim_name,
                    "message": f"正在审校第{ch_num}章 - {dim_name}"
                })

                # 读取当前章节全文
                content = self._read_chapter(ch_num)
                if not content:
                    continue

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

                # 构建prompt
                system_prompt = (
                    f"你是一位专业的小说审校编辑。当前审校维度：{dim_desc}\n\n"
                    f"要求：\n"
                    f"1. 基于当前维度检查并修改章节内容\n"
                    f"2. 保留原有故事情节和人物关系\n"
                    f"3. 保留章节标题（第X章 ...）\n"
                    f"4. 直接输出修改后的完整章节全文，用中文撰写，不要输出JSON、分析报告或英文内容\n"
                    f"5. 如果当前维度没有问题，原样输出章节内容\n"
                    f"6. 你的输出将直接替换原章节文件，因此必须是一篇完整的中文小说章节\n\n"
                    + "\n\n".join(context_parts)
                )
                user_prompt = f"【第{ch_num}章原文】\n{content}\n\n请基于「{dim_name}」维度审校并修改上述章节。{dim_desc}。注意：必须输出完整的中文小说章节全文，不要输出分析报告。"

                # 调用LLM
                if self.llm.has_valid_config("writer"):
                    new_content = await self.llm.call("writer", system_prompt, user_prompt)
                else:
                    continue

                # 尝试从markdown代码块中提取内容（LLM可能用```包裹）
                if new_content and len(re.findall(r'[\u4e00-\u9fff]', new_content)) == 0:
                    code_block_match = re.search(r'```(?:markdown|md|text)?\s*\n([\s\S]*?)\n```', new_content)
                    if code_block_match:
                        new_content = code_block_match.group(1)

                # 内容变空/缩水检测
                if not new_content or not new_content.strip():
                    self._emit({"status": "warning", "message": f"第{ch_num}章{dim_name}审校后内容为空，跳过"})
                    dimensions_done.add(done_key)
                    self.state.data.setdefault("review", {}).setdefault("dimensions_done", []).append(done_key)
                    self.state.save()
                    continue

                original_cn = len(re.findall(r'[\u4e00-\u9fff]', content))
                new_cn = len(re.findall(r'[\u4e00-\u9fff]', new_content))
                if new_cn < original_cn * 0.5 and original_cn > 500:
                    self._emit({"status": "warning", "message": f"第{ch_num}章{dim_name}审校后字数大幅缩水({new_cn}←{original_cn})，跳过"})
                    dimensions_done.add(done_key)
                    self.state.data.setdefault("review", {}).setdefault("dimensions_done", []).append(done_key)
                    self.state.save()
                    continue

                # 判断是否有实质修改并生成报告
                content_changed = new_content.strip() != content.strip()
                if content_changed:
                    diff_cn = new_cn - original_cn
                    sign = "+" if diff_cn >= 0 else ""
                    # 生成简洁的修改摘要
                    old_lines = content.splitlines()
                    new_lines = new_content.splitlines()
                    diff = list(difflib.unified_diff(old_lines, new_lines, lineterm='', n=0))
                    added = [l[1:].strip() for l in diff if l.startswith('+') and not l.startswith('+++')]
                    removed = [l[1:].strip() for l in diff if l.startswith('-') and not l.startswith('---')]
                    report_parts = [f"第{ch_num}章{dim_name}审校完成，已修改（{sign}{diff_cn}字）"]
                    if removed:
                        sample_removed = removed[:3]
                        report_parts.append(f"删除{len(removed)}行，如：{'；'.join(sample_removed[:2])}")
                    if added:
                        sample_added = added[:3]
                        report_parts.append(f"新增{len(added)}行，如：{'；'.join(sample_added[:2])}")
                    self._emit({"status": "review_dim_done", "chapter": ch_num, "dimension": dim_key, "dimension_name": dim_name, "changed": True, "message": "，".join(report_parts)})
                else:
                    self._emit({"status": "review_dim_done", "chapter": ch_num, "dimension": dim_key, "dimension_name": dim_name, "changed": False, "message": f"第{ch_num}章{dim_name}审校完成，无需修改"})

                # 写回章节文件
                self._write_atomic(self._chapter_path(ch_num), new_content)

                # 同步更新数据库标题
                try:
                    from project_db import ProjectDB
                    db = ProjectDB(self.project_name)
                    title = self._extract_chapter_title(new_content)
                    db.upsert_chapter(chapter_index=ch_num, title=title, status="reviewed")
                    db.close()
                except Exception as e:
                    self._emit({"status": "warning", "message": f"第{ch_num}章DB标题同步失败: {e}"})

                # 简单硬性检查
                has_title = bool(re.match(r'#?\s*第\d+章', new_content))
                word_ratio = new_cn / original_cn if original_cn > 0 else 1.0

                results[f"ch{ch_num}_{dim_key}"] = {
                    "chapter": ch_num,
                    "dimension": dim_name,
                    "word_ratio": round(word_ratio, 2),
                    "has_title": has_title,
                    "passed": has_title and word_ratio >= 0.8,
                }

                dimensions_done.add(done_key)
                self.state.data.setdefault("review", {}).setdefault("dimensions_done", []).append(done_key)
                self.state.save()

            if was_cancelled:
                break

        # 根据是否被取消设置不同状态
        if was_cancelled:
            self.state.review_set_status("paused")
            # 保持 current_stage 为 review，不改为 completed
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
            "dimensions_done": review_state.get("dimensions_done", []),
        }
