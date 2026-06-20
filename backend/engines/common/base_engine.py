"""BaseEngine — 三引擎共享的 MWR 循环骨架。"""

import logging
import os
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

from .llm_client import LLMClient
from .kg_adapter import KGAdapter
from .state import EngineState
from .genre_adapter import GenreAdapter
from .hallucination_guard import HallucinationGuardAdapter
from .prompts import get_formatted_prompts, ENGINE_CONFIG


@dataclass
class MWRTask:
    """Manager 分配给 Writer/Reviewer 的任务。"""
    action: str                    # "write" | "polish" | "review"
    layer: str = ""                # L1/L2/L3（大纲引擎用）
    chapter_num: int = 0           # 章节号（写作引擎用）
    dimension: str = ""            # 审校维度（审校引擎用）
    focus_issues: List[str] = field(default_factory=list)  # 上一轮 Reviewer 反馈
    context: str = ""              # 额外上下文


@dataclass
class Draft:
    """Writer 产出的草稿。"""
    content: str = ""              # markdown 正文
    json_data: Dict = field(default_factory=dict)  # 结构化数据
    layer: str = ""                # L1/L2/L3
    chapter_num: int = 0           # 章节号
    metadata: Dict = field(default_factory=dict)


@dataclass
class ReviewResult:
    """Reviewer 评审结果。"""
    score: float = 0.0            # 0-10
    issues: List[str] = field(default_factory=list)
    suggestions: List[str] = field(default_factory=list)
    all_required_passed: bool = False  # 硬性校验是否全过
    hallucination_warnings: List[str] = field(default_factory=list)  # 幻觉警告
    raw_response: str = ""


@dataclass
class FinalDecision:
    """Manager 最终决策。"""
    accepted: bool = True
    reason: str = ""


class BaseEngine:
    """三引擎共享的 MWR 循环骨架。

    子类只需实现 4 个方法：
    - manager_decide(round_num) -> MWRTask
    - writer_execute(task) -> Draft
    - reviewer_evaluate(draft) -> ReviewResult
    - manager_final_decision() -> FinalDecision
    """

    def __init__(self, project_dir: str, project_name: str,
                 project_presets: Optional[Dict[str, Dict]] = None,
                 global_presets: Optional[List[Dict]] = None,
                 kg=None,
                 yield_func=None,
                 genre: str = ""):
        self.project_dir = project_dir
        self.project_name = project_name
        self.engine_name = self.__class__.__name__
        self.llm = LLMClient(project_presets=project_presets,
                             global_presets=global_presets)
        self.kg_adapter = KGAdapter(kg=kg, project_dir=project_dir)
        self.state = EngineState(project_dir)
        self.genre_adapter = GenreAdapter(genre_name=genre)
        self.yield_func = yield_func or (lambda x: None)
        self.cancelled = False  # 外部可设置，用于中断 MWR 循环

        # 引擎配置与提示词（深拷贝避免污染全局 ENGINE_CONFIG）
        self.mode_config = dict(ENGINE_CONFIG)
        self.prompts = get_formatted_prompts()

        # 从项目DB读取项目级配置，覆盖全局默认值
        try:
            from project_db import ProjectDB
            db = ProjectDB(project_name)
            proj = db.get_project()
            if proj:
                for key in ("word_count_min", "word_count_max", "max_rounds_writing", "max_rounds_outline", "max_polish_rounds"):
                    val = proj.get(key)
                    if val is not None:
                        self.mode_config[key] = int(val)
        except Exception as e:
            self._emit({"status": "warning", "message": f"读取项目配置失败，使用默认值: {e}"})

        # 使用项目级字数配置创建 HallucinationGuardAdapter（实例级，不污染类属性）
        self.hallucination_guard = HallucinationGuardAdapter(
            word_count_min=self.mode_config["word_count_min"],
            word_count_max=self.mode_config["word_count_max"],
        )

    def _emit(self, data: Dict):
        """发送状态更新。"""
        if self.yield_func:
            self.yield_func(data)

    # ---- 公共文件操作（子类共享，避免重复代码）----

    def _chapter_path(self, chapter_num: int) -> str:
        """获取章节文件路径，确保目录存在。"""
        d = os.path.join(self.project_dir, "chapters")
        os.makedirs(d, exist_ok=True)
        return os.path.join(d, f"第{chapter_num}章.txt")

    def _write_atomic(self, path: str, content: str):
        """原子写入文件：先写 .tmp，再 os.replace 替换。"""
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(content)
        os.replace(tmp, path)

    def _read_chapter(self, chapter_num: int) -> str:
        """读取指定章节全文，不存在则返回空字符串。"""
        path = self._chapter_path(chapter_num)
        if os.path.isfile(path):
            with open(path, "r", encoding="utf-8") as f:
                return f.read()
        return ""

    def _clean_fs_ids(self, content: str) -> str:
        """清洗 LLM 输出中的 FS 编号（如 FS-001、FS-002-Variant 等）。"""
        content = re.sub(r"\bFS-\d+(?:-\d+)?(?:-Variant)?\b", "", content)
        content = re.sub(r"[（(]\s*[）)]", "", content)
        return content

    # 省略号替换标点：按顺序轮换使用
    # 不用短语替换！短语（如"沉默了片刻"、"深吸了一口气"）本身就是AI痕迹
    # 用标点替换更自然：逗号=停顿，句号=结束，破折号=转折，感叹号=情绪
    _ELLIPSIS_REPLACEMENTS = [
        "，",
        "——",
        "。",
        "！",
        "，",
        "——",
        "。",
        "！",
    ]

    def _reduce_ellipsis(self, content: str, max_ellipsis: int = 5) -> str:
        """程序化替换多余省略号。

        LLM 几乎无法自行减少省略号（日志显示50→43，润色4轮仍不达标），
        因此必须在写作/润色后程序化处理。

        策略：保留前 max_ellipsis 个省略号，多余的替换为标点。
        不用短语替换——短语本身就是AI痕迹，会被Reviewer标记。
        """
        ellipsis_pattern = re.compile(r'……|\.\.\.\.\.\.')
        matches = list(ellipsis_pattern.finditer(content))

        if len(matches) <= max_ellipsis:
            return content

        # 从后往前替换（避免索引漂移），保留前 max_ellipsis 个
        replace_count = len(matches) - max_ellipsis
        self._emit({"status": "info", "message":
            f"省略号{len(matches)}个超过上限{max_ellipsis}，程序化替换{replace_count}个"})

        result = content
        replacement_idx = 0
        for match in reversed(matches[max_ellipsis:]):
            replacement = self._ELLIPSIS_REPLACEMENTS[
                replacement_idx % len(self._ELLIPSIS_REPLACEMENTS)]
            result = result[:match.start()] + replacement + result[match.end():]
            replacement_idx += 1

        return result

    # ─── 多层后处理流水线 ──────────────────────────────────
    # 专业方法：程序化后处理优先于LLM自我修正
    # 参考：Sudowrite / NovelAI / AI_NovelGenerator 的最佳实践

    # Layer 2: 对话标签多样化
    _SAID_VARIANTS = [
        "道", "沉声道", "冷声道", "低声道", "叹了口气",
        "反问", "追问", "嘟囔", "嘀咕", "笑道",
        "苦笑", "厉声道", "轻声道", "嗤笑", "冷哼",
    ]

    def _diversify_dialogue_tags(self, content: str, max_said: int = 3) -> str:
        """对话标签多样化：同一章内"说道"出现不超过 max_said 次，超出部分随机替换。

        LLM 倾向于反复使用"说道"，这是最典型的AI痕迹之一。
        程序化替换比让LLM自己改更可靠。
        """
        # 匹配 "X说道" "X说道：" 等模式
        said_pattern = re.compile(r'说道[：:]?')
        matches = list(said_pattern.finditer(content))

        if len(matches) <= max_said:
            return content

        replace_count = len(matches) - max_said
        self._emit({"status": "info", "message":
            f"对话标签'说道'出现{len(matches)}次超过上限{max_said}，替换{replace_count}个"})

        import random
        result = content
        # 从后往前替换，避免索引漂移
        for i, match in enumerate(reversed(matches[max_said:])):
            variant = self._SAID_VARIANTS[random.randint(0, len(self._SAID_VARIANTS) - 1)]
            # 如果原文是"说道："，替换为"variant："
            if match.group().endswith('：') or match.group().endswith(':'):
                variant += '：'
            result = result[:match.start()] + variant + result[match.end():]

        return result

    # Layer 3: AI高频短语黑名单替换
    _AI_PHRASE_BLACKLIST = {
        "心中一震": ["心里咯噔一下", "愣住了", "瞳孔一缩"],
        "不禁感叹": ["叹了口气", "摇了摇头", "感慨万千"],
        "与此同时": ["这会儿", "另一边", "就在这时"],
        "值得注意的是": [],
        "综上所述": [],
        "由此可见": [],
        "颇为": ["挺", "蛮", "相当"],
        "甚是": ["很", "特别", "非常"],
        "不禁": ["忍不住", "下意识"],
        "心中暗道": ["心想", "暗想", "心下思忖"],
        "嘴角微微上扬": ["嘴角一勾", "笑了", "咧嘴一笑"],
        "眼中闪过一丝": ["眼里掠过", "目光一闪", "眸光微动"],
        # LLM 高频生成的省略号替换残留 / 模板短语
        "沉默了片刻": ["顿了顿", "停了一拍"],
        "深吸了一口气": ["吸了口气", "长出一口气"],
    }

    def _replace_ai_phrases(self, content: str) -> str:
        """AI高频短语黑名单替换。

        这些短语是LLM的"指纹"，人类作者极少使用。
        程序化替换比让LLM自己避免更可靠。
        """
        changes = 0
        for phrase, replacements in self._AI_PHRASE_BLACKLIST.items():
            count = content.count(phrase)
            if count > 0:
                if replacements:
                    import random
                    replacement = replacements[random.randint(0, len(replacements) - 1)]
                    content = content.replace(phrase, replacement)
                else:
                    # 空列表 = 直接删除
                    content = content.replace(phrase, "")
                changes += count

        if changes > 0:
            self._emit({"status": "info", "message": f"替换{changes}个AI高频短语"})

        return content

    # Layer 4: 句长波动注入（burstiness提升）
    def _inject_sentence_variation(self, content: str) -> str:
        """句长波动注入：检测连续短句或连续长句，适当合并或拆分。

        AI生成的句子长度趋于均匀（15-25字），人类写作则长短错落。
        提升burstiness指标可以让文本更像人写的。
        """
        # 按段落处理，避免跨段落操作
        paragraphs = content.split("\n\n")
        result = []

        for para in paragraphs:
            if not para.strip():
                result.append(para)
                continue

            # 按中文句号/问号/感叹号分句
            sentences = re.split(r'([。！？])', para)
            # 重组（保留标点）
            sent_list = []
            for i in range(0, len(sentences) - 1, 2):
                s = sentences[i] + (sentences[i + 1] if i + 1 < len(sentences) else '')
                if s.strip():
                    sent_list.append(s)
            if len(sentences) % 2 == 1 and sentences[-1].strip():
                sent_list.append(sentences[-1])

            if len(sent_list) < 3:
                result.append(para)
                continue

            # 检测连续短句（<8字）超过3个 → 合并为一句
            merged = []
            short_run = []
            for s in sent_list:
                cn_chars = len(re.findall(r'[\u4e00-\u9fff]', s))
                if cn_chars < 8:
                    short_run.append(s)
                    if len(short_run) >= 3:
                        # 合并：去掉中间的句号，用逗号连接
                        merged_sent = short_run[0][:-1] + "，"
                        for mid in short_run[1:-1]:
                            merged_sent += mid[:-1] + "，"
                        merged_sent += short_run[-1]
                        merged.append(merged_sent)
                        short_run = []
                else:
                    if short_run:
                        merged.extend(short_run)
                        short_run = []
                    merged.append(s)
            if short_run:
                merged.extend(short_run)

            result.append("".join(merged))

        return "\n\n".join(result)

    def _post_process(self, content: str) -> str:
        """多层后处理流水线入口。

        执行顺序：
        1. 省略号配额管理（_reduce_ellipsis）
        2. 对话标签多样化（_diversify_dialogue_tags）
        3. AI高频短语替换（_replace_ai_phrases）
        4. 句长波动注入（_inject_sentence_variation）
        5. 去重（_deduplicate_paragraphs，在子类中调用）

        原则：能用规则解决的问题不要交给LLM。
        """
        content = self._reduce_ellipsis(content)
        content = self._diversify_dialogue_tags(content)
        content = self._replace_ai_phrases(content)
        content = self._inject_sentence_variation(content)
        return content

    def _read_recent_chapters(self, n: int = 3) -> str:
        """读取最近章节上下文：前2章给结尾摘要，紧邻章给全文以保证完美衔接。"""
        parts = []
        start = max(1, self._current_chapter - n)
        for ch in range(start, self._current_chapter):
            is_adjacent = (ch == self._current_chapter - 1)
            content = self._read_chapter(ch)
            if content:
                content = self._clean_fs_ids(content)
                if is_adjacent:
                    # 紧邻章：注入全文，保证完美衔接
                    parts.append(f"【第{ch}章·全文 — 必须自然衔接】\n{content}")
                else:
                    # 前2章：只注入结尾段落（KG 前情提要在融合记忆中已全局覆盖）
                    tail_len = 500
                    if len(content) > tail_len:
                        content = f"[前文摘要]\n{content[-tail_len:]}"
                    parts.append(f"【第{ch}章·结尾】\n{content}")
        return "\n\n".join(parts)

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

    async def run_mwr_cycle(self, max_rounds: int = 5,
                            score_threshold: float = 8.0) -> ReviewResult:
        """通用 MWR 循环。

        1. Manager 决定本轮任务
        2. Writer 执行
        3. Reviewer 评审
        4. 如果 score >= threshold 且硬性校验全过 → 停止
        5. 否则 Manager 把 Reviewer 反馈传给 Writer 修改
        6. 连续 N 轮评分无提升 → 卡住，停止
        """
        last_result = None
        self._issue_consecutive_counts = {}
        best_score = 0.0
        recent_scores = []  # 滑动窗口：记录未超过best_score的轮次
        NO_IMPROVE_WINDOW = 5  # 最近5轮无提升则认为卡住（放宽，给LLM更多修改机会）
        consecutive_llm_errors = 0  # 连续LLM错误计数

        round_num = 0
        while True:
            round_num += 1
            logger.info("MWR cycle started: %s round %d", self.engine_name, round_num)

            # 润色轮次硬上限（使用传入的 max_rounds 参数）
            if round_num > max_rounds:
                self._emit({"status": "cycle_max_rounds", "round": round_num, "reason": f"达到润色轮次上限({max_rounds})"})
                break

            # 检查是否已被用户取消
            if self.cancelled:
                logger.info("MWR cycle cancelled: %s", self.engine_name)
                self._emit({"status": "cycle_cancelled", "round": round_num, "reason": "用户取消"})
                return last_result or ReviewResult(score=0.0, issues=["用户取消"])

            self._emit({"status": "mwr_round", "round": round_num, "max_rounds": max_rounds})

            # 1. Manager 决定任务
            task = self.manager_decide(round_num, last_result)
            self._emit({"status": "manager_decided", "round": round_num, "action": task.action})

            # accept_current：润色用尽，走 final_decision 钩子后结束循环
            if task.action == "accept_current":
                self._emit({"status": "cycle_ended", "accepted": True, "reason": "润色次数用尽，接受当前内容"})
                final = self.manager_final_decision()
                if final.accepted:
                    self._on_cycle_completed(round_num, last_result)
                return last_result or ReviewResult(score=0.0, issues=["润色用尽"])

            # 2. Writer 执行
            draft = await self.writer_execute(task)
            self._emit({"status": "writer_done", "round": round_num})

            # 3. Reviewer 评审
            result = await self.reviewer_evaluate(draft)
            last_result = result
            self._emit({
                "status": "reviewer_done", "round": round_num,
                "score": result.score, "issues": result.issues,
                "all_required_passed": result.all_required_passed,
            })

            # 3.5 连续LLM错误检测：连续3轮score=0且all_required_passed=false，停止循环
            if result.score == 0.0 and not result.all_required_passed:
                consecutive_llm_errors += 1
                logger.error("MWR LLM error: %s round %d", self.engine_name, round_num)
                if consecutive_llm_errors >= 3:
                    self._emit({"status": "cycle_stuck", "round": round_num,
                                "reason": f"连续{consecutive_llm_errors}轮LLM错误/空内容，停止循环"})
                    break
            else:
                consecutive_llm_errors = 0

            # 4. 判断是否通过
            if result.score >= score_threshold and result.all_required_passed:
                logger.info("MWR cycle passed: %s score=%.1f", self.engine_name, result.score)
                self._on_cycle_completed(round_num, result)
                self._emit({"status": "cycle_completed", "round": round_num, "score": result.score})
                return result

            # 5. 卡住检测（滑动窗口）：只发警告不退出（依赖 max_rounds 兜底）
            if result.score > best_score:
                best_score = result.score
                recent_scores = []  # 有提升，重置窗口
            else:
                recent_scores.append(result.score)

            if len(recent_scores) >= NO_IMPROVE_WINDOW:
                logger.warning("MWR cycle stuck: %s after %d rounds", self.engine_name, round_num)
                self._emit({"status": "warning", "round": round_num,
                            "message": f"连续{NO_IMPROVE_WINDOW}轮评分无提升（最高{best_score:.1f}），继续尝试修改"})
                recent_scores = []  # 重置窗口，给 LLM 更多机会

            # 6. 连续相同问题检测：只发警告不退出（依赖 max_rounds 兜底）
            if result.score < score_threshold or not result.all_required_passed:
                current_issues_set = set(result.issues)
                new_issue_counts = {}
                for issue in current_issues_set:
                    new_issue_counts[issue] = self._issue_consecutive_counts.get(issue, 0) + 1
                self._issue_consecutive_counts = new_issue_counts
                stuck_issues = [iss for iss, cnt in self._issue_consecutive_counts.items() if cnt >= 3]
                if stuck_issues:
                    self._emit({"status": "warning", "round": round_num,
                                "message": f"连续3轮未解决问题: {stuck_issues[:3]}，继续尝试修改"})
                    # 不再退出，只发警告，依赖 max_rounds 兜底
            else:
                self._issue_consecutive_counts = {}

        # 循环结束
        final = self.manager_final_decision()
        if final.accepted:
            self._on_cycle_completed(round_num, last_result)
        self._emit({"status": "cycle_ended", "accepted": final.accepted, "reason": final.reason})
        return last_result or ReviewResult(score=0.0, issues=["循环结束且无评审结果"])

    def manager_decide(self, round_num: int, last_result: Optional[ReviewResult] = None) -> MWRTask:
        """Manager 决定本轮任务。子类使用 MWR 循环时必须实现。"""
        raise NotImplementedError("Subclass using MWR cycle must implement manager_decide")

    async def writer_execute(self, task: MWRTask) -> Draft:
        """Writer 执行写作任务。子类使用 MWR 循环时必须实现。"""
        raise NotImplementedError("Subclass using MWR cycle must implement writer_execute")

    async def reviewer_evaluate(self, draft: Draft) -> ReviewResult:
        """Reviewer 评审草稿。子类使用 MWR 循环时必须实现。"""
        raise NotImplementedError("Subclass using MWR cycle must implement reviewer_evaluate")

    def manager_final_decision(self) -> FinalDecision:
        """Manager 最终决策（达到轮数上限时）。子类使用 MWR 循环时必须实现。"""
        raise NotImplementedError("Subclass using MWR cycle must implement manager_final_decision")

    def _on_cycle_completed(self, round_num: int, result: ReviewResult):
        """循环完成后的钩子（子类可覆盖）。"""
        pass
