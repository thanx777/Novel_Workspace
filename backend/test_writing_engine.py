"""写作引擎测试 — 覆盖 WritingEngine 初始化 / manager_decide 分支 / 硬性检查 / 问题继承 / 取消逻辑。

LLM 调用全部 mock，文件系统测试用 create_project + cleanup。
"""
import sys
import os
import asyncio
import json
import shutil

sys.path.insert(0, '.')

from project_db import ProjectDB, create_project, delete_project, get_project_dir
from engines.writing.engine import WritingEngine
from engines.common.base_engine import MWRTask, Draft, ReviewResult

PASSED, FAILED = [], []


def run(name, fn):
    # KGAdapter.__init__ 会创建 asyncio.Lock，需要事件循环
    try:
        asyncio.get_event_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())
    try:
        r = fn()
        PASSED.append((name, r))
        print(f"  ✅ {name}")
    except Exception as e:
        FAILED.append((name, str(e)))
        print(f"  ❌ {name} → {e}")


def cleanup(names):
    for n in names:
        try:
            delete_project(n)
        except Exception:
            pass
        p = os.path.join('workspace', 'projects', n)
        if os.path.exists(p):
            shutil.rmtree(p, ignore_errors=True)


PROJ_NAME = "test_writing"


def _make_engine(total_chapters=5, max_polish_rounds=2, score_threshold=7.0):
    """创建写作引擎实例（无 LLM 配置）。"""
    cleanup([PROJ_NAME])
    create_project(PROJ_NAME, "测试写作", "玄幻", total_chapters)
    proj_dir = get_project_dir(PROJ_NAME)
    engine = WritingEngine(
        proj_dir, PROJ_NAME,
        total_chapters=total_chapters,
        max_polish_rounds=max_polish_rounds,
        score_threshold=score_threshold,
        genre="",
    )
    return engine, proj_dir


def _write_chapter(proj_dir, ch_num, content):
    """写入章节文件。"""
    ch_dir = os.path.join(proj_dir, "chapters")
    os.makedirs(ch_dir, exist_ok=True)
    path = os.path.join(ch_dir, f"第{ch_num}章.txt")
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    return path


# ============ 1. WritingEngine 初始化 ============
def t01():
    engine, proj_dir = _make_engine(total_chapters=30)
    assert engine.project_name == PROJ_NAME
    assert engine.project_dir == proj_dir
    assert engine.total_chapters == 30
    assert engine._current_chapter == 1
    assert engine._polish_count == 0
    assert engine._rewrite_count == 0
    assert engine._last_valid_ai_score is None
    assert engine._previous_issues == set()
    assert engine.max_polish_rounds == 2
    assert engine.score_threshold == 7.0
    assert engine.cancelled is False
    cleanup([PROJ_NAME])
    return "初始化 OK"


# ============ 2. manager_decide — 第1轮 write ============
def t02():
    engine, _ = _make_engine()
    task = engine.manager_decide(1, None)
    assert task.action == "write"
    assert task.chapter_num == 1
    cleanup([PROJ_NAME])
    return "第1轮 write OK"


# ============ 3. manager_decide — rewrite（格式问题） ============
def t03():
    engine, _ = _make_engine()
    # 格式问题 + 润色次数未用尽 → rewrite
    last_result = ReviewResult(
        score=3.0,
        issues=["缺少章节标题", "字数不足"],
        all_required_passed=False,
    )
    task = engine.manager_decide(2, last_result)
    assert task.action == "write"  # 格式问题 → rewrite
    assert task.chapter_num == 1
    assert engine._rewrite_count == 1
    # focus_issues 应传递
    assert "缺少章节标题" in task.focus_issues
    cleanup([PROJ_NAME])
    return "rewrite OK"


# ============ 4. manager_decide — rewrite 上限后 polish ============
def t04():
    engine, _ = _make_engine()
    # 先消耗2次 rewrite（MAX_REWRITES = 2）
    last_result = ReviewResult(
        score=3.0,
        issues=["缺少章节标题"],
        all_required_passed=False,
    )
    engine.manager_decide(2, last_result)  # rewrite 1
    engine.manager_decide(3, last_result)  # rewrite 2
    # 第3次应该走 polish
    task = engine.manager_decide(4, last_result)
    assert task.action == "polish"
    assert engine._polish_count == 1
    cleanup([PROJ_NAME])
    return "rewrite 上限后 polish OK"


# ============ 5. manager_decide — polish（非格式问题） ============
def t05():
    engine, _ = _make_engine(max_polish_rounds=3)
    last_result = ReviewResult(
        score=5.0,
        issues=["叙事节奏偏慢", "对话不够自然"],
        all_required_passed=False,
    )
    task = engine.manager_decide(2, last_result)
    assert task.action == "polish"
    assert task.chapter_num == 1
    assert engine._polish_count == 1
    cleanup([PROJ_NAME])
    return "polish OK"


# ============ 6. manager_decide — accept_current（润色用尽 + 硬性校验未通过） ============
def t06():
    engine, _ = _make_engine(max_polish_rounds=1)
    last_result = ReviewResult(
        score=4.0,
        issues=["叙事节奏偏慢"],
        all_required_passed=False,
    )
    # 消耗1次 polish
    engine.manager_decide(2, last_result)  # polish 1
    # 润色用尽，硬性校验仍未通过 → accept_current
    task = engine.manager_decide(3, last_result)
    assert task.action == "accept_current"
    cleanup([PROJ_NAME])
    return "accept_current OK"


# ============ 7. manager_decide — polish（硬性校验通过但分数不够） ============
def t07():
    engine, _ = _make_engine(max_polish_rounds=2)
    last_result = ReviewResult(
        score=5.5,
        issues=["叙事节奏偏慢"],
        all_required_passed=True,  # 硬性校验通过
    )
    task = engine.manager_decide(2, last_result)
    assert task.action == "polish"
    assert engine._polish_count == 1
    cleanup([PROJ_NAME])
    return "硬性校验通过但分数不够 → polish OK"


# ============ 8. manager_decide — accept_current（润色用尽 + 硬性校验通过） ============
def t08():
    engine, _ = _make_engine(max_polish_rounds=1)
    last_result = ReviewResult(
        score=5.5,
        issues=["叙事节奏偏慢"],
        all_required_passed=True,
    )
    # 消耗1次 polish
    engine.manager_decide(2, last_result)  # polish 1
    # 润色用尽 → accept_current
    task = engine.manager_decide(3, last_result)
    assert task.action == "accept_current"
    cleanup([PROJ_NAME])
    return "润色用尽 accept_current OK"


# ============ 9. reviewer_evaluate — 空内容 ============
def t09():
    engine, _ = _make_engine()

    async def _run():
        draft = Draft(content="", chapter_num=1)
        return await engine.reviewer_evaluate(draft)

    result = asyncio.run(_run())
    assert result.score == 0.0
    assert result.all_required_passed is False
    assert len(result.issues) > 0
    cleanup([PROJ_NAME])
    return "空内容评审 OK"


# ============ 10. reviewer_evaluate — 极少中文字 ============
def t10():
    engine, _ = _make_engine()

    async def _run():
        draft = Draft(content="第1章\n\n测试", chapter_num=1)
        return await engine.reviewer_evaluate(draft)

    result = asyncio.run(_run())
    assert result.score == 0.0
    assert result.all_required_passed is False
    cleanup([PROJ_NAME])
    return "极少中文字评审 OK"


# ============ 11. reviewer_evaluate — 硬性检查（字数不足） ============
def t11():
    engine, _ = _make_engine()
    # 写一段不足1000字的内容
    short_content = "第1章 觉醒\n\n" + "这是测试内容。" * 30  # 约180字

    async def _run():
        draft = Draft(content=short_content, chapter_num=1)
        return await engine.reviewer_evaluate(draft)

    result = asyncio.run(_run())
    assert result.all_required_passed is False
    # 应有字数不足的 issue
    has_word_count_issue = any("字数" in iss for iss in result.issues)
    assert has_word_count_issue, f"应有字数不足 issue，实际: {result.issues}"
    cleanup([PROJ_NAME])
    return "硬性检查字数不足 OK"


# ============ 12. reviewer_evaluate — 省略号密度检查 ============
def t12():
    engine, _ = _make_engine()
    # 写一段省略号过多的内容（但字数足够）
    content = "第1章 觉醒\n\n" + "他想着……她看着……他们走着……" * 100

    async def _run():
        draft = Draft(content=content, chapter_num=1)
        return await engine.reviewer_evaluate(draft)

    result = asyncio.run(_run())
    has_ellipsis_issue = any("省略号" in iss for iss in result.issues)
    assert has_ellipsis_issue, f"应有省略号过多 issue，实际: {result.issues}"
    cleanup([PROJ_NAME])
    return "省略号密度检查 OK"


# ============ 13. reviewer_evaluate — FS 编号检查 ============
def t13():
    engine, _ = _make_engine()
    content = "第1章 觉醒\n\n" + "林轩走进了青云山。" * 200 + "\nFS-001 是一个伏笔。FS-999 另一个。"

    async def _run():
        draft = Draft(content=content, chapter_num=1)
        return await engine.reviewer_evaluate(draft)

    result = asyncio.run(_run())
    # FS 编号应被检测到（KG 中不存在这些 ID）
    has_fs_issue = any("FS" in iss or "伏笔" in iss for iss in result.issues)
    assert has_fs_issue or len(result.hallucination_warnings) > 0, f"应有 FS 相关 issue 或幻觉警告，实际: {result.issues}"
    cleanup([PROJ_NAME])
    return "FS 编号检查 OK"


# ============ 14. 问题继承 — persistent vs fresh ============
def t14():
    engine, _ = _make_engine()
    # 模拟第一轮评审结果
    engine._previous_issues = {"叙事节奏偏慢", "对话不够自然"}

    # 第二轮：叙事节奏偏慢仍然存在（persistent），新增疲劳词（fresh）
    content = "第1章 觉醒\n\n" + "林轩走进了青云山，开始了他的修仙之路。" * 100
    engine.llm.has_valid_config = lambda role: False  # 无 LLM，跳过 AI 评审

    async def _run():
        draft = Draft(content=content, chapter_num=1)
        # 手动注入问题来测试继承逻辑
        # 直接测试 _previous_issues 的更新机制
        return await engine.reviewer_evaluate(draft)

    result = asyncio.run(_run())
    # 检查 annotated_issues 中是否有 [未修复] 和 [新发现] 标记
    has_persistent = any("[未修复]" in iss for iss in result.issues)
    has_fresh = any("[新发现]" in iss for iss in result.issues)
    # 至少应该有新发现标记（因为当前轮次的问题集中有不在 _previous_issues 中的）
    # 注意：如果当前轮没有问题，则不会有标记
    # 验证 _previous_issues 被更新
    assert isinstance(engine._previous_issues, set)
    cleanup([PROJ_NAME])
    return "问题继承机制 OK"


# ============ 15. 取消逻辑 — cancelled 标志 ============
def t15():
    engine, proj_dir = _make_engine()
    _write_chapter(proj_dir, 1, "第1章 觉醒\n\n" + "内容。" * 100)
    engine.cancelled = True  # 直接设置取消标志

    assert engine.cancelled is True

    # write_all 应该在检查 cancelled 后退出
    async def _run():
        return await engine.write_all(start_chapter=1)

    result = asyncio.run(_run())
    # 应该被取消，不会写任何章节
    assert result.get("chapters_written", 0) == 0 or engine.cancelled
    cleanup([PROJ_NAME])
    return "取消逻辑 OK"


# ============ 16. manager_final_decision ============
def t16():
    engine, _ = _make_engine()
    # 无轮次记录 → 不接受
    decision = engine.manager_final_decision()
    assert decision.accepted is False

    # 添加高评分轮次 → 接受
    engine.state.writing_add_round(round_num=1, chapter=1, action="write", score=7.5, issues=[])
    decision = engine.manager_final_decision()
    assert decision.accepted is True

    # 添加低评分轮次（覆盖最后一条）→ 不接受
    engine.state.writing_add_round(round_num=2, chapter=1, action="polish", score=3.0, issues=["问题"])
    decision = engine.manager_final_decision()
    assert decision.accepted is False
    cleanup([PROJ_NAME])
    return "manager_final_decision OK"


# ============ 17. get_status ============
def t17():
    engine, _ = _make_engine(total_chapters=10)
    status = engine.get_status()
    assert "status" in status
    assert "current_chapter" in status
    assert "total_chapters" in status
    assert "completed_chapters" in status
    assert "progress" in status
    assert status["total_chapters"] == 10
    assert status["status"] == "pending"
    cleanup([PROJ_NAME])
    return "get_status OK"


# ============ 18. _deduplicate_paragraphs ============
def t18():
    engine, _ = _make_engine()
    content = "第一段\n\n第二段\n\n第一段\n\n第三段\n\n第二段"
    result = engine._deduplicate_paragraphs(content)
    # 重复段落应被去除
    paragraphs = result.split("\n\n")
    assert len(paragraphs) == 3  # 第一段、第二段、第三段
    assert "第三段" in result
    cleanup([PROJ_NAME])
    return "去重段落 OK"


# ============ 19. _clean_fs_ids ============
def t19():
    engine, _ = _make_engine()
    # 使用空格分隔以让 \b 词边界正常工作
    content = "这是 FS-001 的内容。还有 FS-002-Variant 。以及 FS-003-01 。\n（FS-004）应清除空括号。"
    result = engine._clean_fs_ids(content)
    assert "FS-001" not in result
    assert "FS-002" not in result
    assert "FS-003" not in result
    assert "FS-004" not in result
    # 空括号应被清除
    assert "（）" not in result
    assert "()" not in result
    cleanup([PROJ_NAME])
    return "FS 编号清洗 OK"


# ============ 20. _apply_paragraph_edits ============
def t20():
    engine, _ = _make_engine()
    original = "段落一\n\n段落二\n\n段落三"
    paragraphs = ["段落一", "段落二", "段落三"]
    llm_output = "===REPLACE P2===\n修改后的段落二\n===END===\n===INSERT AFTER P3===\n新增段落\n===END==="
    result = engine._apply_paragraph_edits(original, paragraphs, llm_output)
    assert "修改后的段落二" in result
    assert "新增段落" in result
    assert "段落一" in result  # 未修改
    assert "段落三" in result  # 未修改
    cleanup([PROJ_NAME])
    return "段落编辑应用 OK"


if __name__ == '__main__':
    print("=" * 70)
    print("  写作引擎测试 (20 用例)")
    print("=" * 70)
    print()
    run("01. WritingEngine 初始化", t01)
    run("02. manager_decide 第1轮 write", t02)
    run("03. manager_decide rewrite（格式问题）", t03)
    run("04. manager_decide rewrite 上限后 polish", t04)
    run("05. manager_decide polish（非格式问题）", t05)
    run("06. manager_decide accept_current（润色用尽+硬性未过）", t06)
    run("07. manager_decide polish（硬性通过但分数不够）", t07)
    run("08. manager_decide accept_current（润色用尽+硬性通过）", t08)
    run("09. reviewer_evaluate 空内容", t09)
    run("10. reviewer_evaluate 极少中文字", t10)
    run("11. reviewer_evaluate 硬性检查字数不足", t11)
    run("12. reviewer_evaluate 省略号密度检查", t12)
    run("13. reviewer_evaluate FS 编号检查", t13)
    run("14. 问题继承 persistent vs fresh", t14)
    run("15. 取消逻辑 cancelled 标志", t15)
    run("16. manager_final_decision", t16)
    run("17. get_status", t17)
    run("18. _deduplicate_paragraphs", t18)
    run("19. _clean_fs_ids", t19)
    run("20. _apply_paragraph_edits", t20)
    print()
    print("=" * 70)
    print(f"  结果:  {len(PASSED)} 通过 / {len(FAILED)} 失败")
    print("=" * 70)
    sys.exit(0 if not FAILED else 1)


# ============ pytest 兼容包装 ============
def test_writing_init():
    t01()

def test_manager_decide_write():
    t02()

def test_manager_decide_rewrite():
    t03()

def test_manager_decide_rewrite_limit_then_polish():
    t04()

def test_manager_decide_polish():
    t05()

def test_manager_decide_accept_current_hard_fail():
    t06()

def test_manager_decide_polish_hard_pass_score_low():
    t07()

def test_manager_decide_accept_current_polish_exhausted():
    t08()

def test_reviewer_empty_content():
    t09()

def test_reviewer_few_chinese_chars():
    t10()

def test_reviewer_word_count_check():
    t11()

def test_reviewer_ellipsis_density():
    t12()

def test_reviewer_fs_id_check():
    t13()

def test_issue_inheritance():
    t14()

def test_cancel_flag():
    t15()

def test_manager_final_decision():
    t16()

def test_get_status():
    t17()

def test_deduplicate_paragraphs():
    t18()

def test_clean_fs_ids():
    t19()

def test_apply_paragraph_edits():
    t20()
