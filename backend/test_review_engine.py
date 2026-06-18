"""审校引擎测试 — 覆盖 ReviewEngine 初始化 / 6 维度常量 / 章节读取 / 内容清洗 / 单维度审校 / 完整流程 / 取消 / 状态。

LLM 调用全部 mock，文件系统测试用 create_project + cleanup。
"""
import sys
import os
import asyncio
import json
import shutil
import re

sys.path.insert(0, '.')

from project_db import ProjectDB, create_project, delete_project, get_project_dir
from engines.review.engine import ReviewEngine, _ALL_REVIEW_DIMENSIONS
from engines.common.base_engine import ReviewResult

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


PROJ_NAME = "test_review"


def _make_engine():
    """创建审校引擎实例（无 LLM 配置）。"""
    cleanup([PROJ_NAME])
    create_project(PROJ_NAME, "测试审校", "玄幻", 5)
    proj_dir = get_project_dir(PROJ_NAME)
    engine = ReviewEngine(
        proj_dir, PROJ_NAME,
        max_rounds_per_dimension=1,
        score_threshold=7.0,
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


# ============ 1. ReviewEngine 初始化 ============
def t01():
    engine, proj_dir = _make_engine()
    assert engine.project_name == PROJ_NAME
    assert engine.project_dir == proj_dir
    assert engine.max_rounds_per_dimension == 1
    assert engine.score_threshold == 7.0
    assert engine._current_dimension == 0
    assert engine._current_chapter == 0
    assert engine._dimensions_done == []
    assert engine.cancelled is False
    cleanup([PROJ_NAME])
    return "初始化 OK"


# ============ 2. 6 维度常量验证 ============
def t02():
    assert len(_ALL_REVIEW_DIMENSIONS) == 6
    keys = [d[0] for d in _ALL_REVIEW_DIMENSIONS]
    expected = ["character_arc", "foreshadowing", "consistency", "style", "coolpoint_hook", "ai_trace"]
    assert keys == expected, f"维度 key 不匹配: {keys}"
    # 每个维度都有 (key, name, desc) 三元组
    for dim_key, dim_name, dim_desc in _ALL_REVIEW_DIMENSIONS:
        assert isinstance(dim_key, str) and len(dim_key) > 0
        assert isinstance(dim_name, str) and len(dim_name) > 0
        assert isinstance(dim_desc, str) and len(dim_desc) > 0
    # 引擎应复制维度列表
    engine, _ = _make_engine()
    assert len(engine._dimensions) == 6
    assert engine._dimensions is not _ALL_REVIEW_DIMENSIONS  # 应是副本
    cleanup([PROJ_NAME])
    return "6 维度常量 OK"


# ============ 3. _get_all_chapters ============
def t03():
    engine, proj_dir = _make_engine()
    # 无章节目录 → 空字典
    chapters = engine._get_all_chapters()
    assert chapters == {}

    # 写入章节
    _write_chapter(proj_dir, 1, "第1章 内容")
    _write_chapter(proj_dir, 2, "第2章 内容")
    _write_chapter(proj_dir, 5, "第5章 内容")

    chapters = engine._get_all_chapters()
    assert len(chapters) == 3
    assert 1 in chapters
    assert 2 in chapters
    assert 5 in chapters
    assert "第1章" in chapters[1]
    assert "第5章" in chapters[5]
    cleanup([PROJ_NAME])
    return "获取章节 OK"


# ============ 4. _get_chapter_summary ============
def t04():
    engine, proj_dir = _make_engine()
    # 不存在的章节 → 空字符串
    assert engine._get_chapter_summary(1) == ""

    # 写入章节
    long_content = "第1章 测试\n\n" + "这是章节内容。" * 50
    _write_chapter(proj_dir, 1, long_content)

    summary = engine._get_chapter_summary(1)
    assert len(summary) <= 300  # 摘要不超过 300 字
    assert "第1章" in summary
    cleanup([PROJ_NAME])
    return "章节摘要 OK"


# ============ 5. _clean_chapter_content — FS 编号清除 ============
def t05():
    engine, _ = _make_engine()
    content = "第1章 测试\n\nFS-001 是伏笔。还有 FS-002-Variant。以及 FS-003-01。\n（FS-004）应清除空括号。"
    result = engine._clean_chapter_content(content)
    assert "FS-001" not in result
    assert "FS-002" not in result
    assert "FS-003" not in result
    assert "FS-004" not in result
    # 空括号应被清除
    assert "（）" not in result
    assert "()" not in result
    cleanup([PROJ_NAME])
    return "FS 编号清除 OK"


# ============ 6. _clean_chapter_content — 标题统一 ============
def t06():
    engine, _ = _make_engine()
    # 第X章：→ 第X章 （冒号变空格）
    content = "# 第1章：觉醒\n\n正文内容。"
    result = engine._clean_chapter_content(content)
    assert "# 第1章 觉醒" in result
    assert "第1章：觉醒" not in result

    # 全角冒号也应处理
    content2 = "## 第2章：试炼\n\n正文。"
    result2 = engine._clean_chapter_content(content2)
    assert "## 第2章 试炼" in result2
    cleanup([PROJ_NAME])
    return "标题统一 OK"


# ============ 7. _clean_chapter_content — 空行压缩 ============
def t07():
    engine, _ = _make_engine()
    # 3+ 连续空行压缩为 1 个空行（即 2 个 \n）
    content = "第1章 测试\n\n\n\n\n正文内容。"
    result = engine._clean_chapter_content(content)
    # 不应有 3+ 连续换行
    assert "\n\n\n" not in result
    assert "正文内容。" in result
    # 结果应以单个换行结尾
    assert result.endswith("\n")
    cleanup([PROJ_NAME])
    return "空行压缩 OK"


# ============ 8. _review_dimension_phase1 — 无 LLM 配置跳过 ============
def t08():
    engine, proj_dir = _make_engine()
    _write_chapter(proj_dir, 1, "第1章 测试\n\n正文内容。")
    engine.llm.has_valid_config = lambda role: False

    async def _run():
        return await engine._review_dimension_phase1(1, "style", "风格统一", "检查风格")

    result = asyncio.run(_run())
    assert result.get("skipped") is True
    assert result.get("reason") == "no_llm_config"
    cleanup([PROJ_NAME])
    return "无 LLM 跳过 OK"


# ============ 9. _review_dimension_phase1 — 空内容跳过 ============
def t09():
    engine, proj_dir = _make_engine()
    # 不写入章节文件 → _read_chapter 返回空
    engine.llm.has_valid_config = lambda role: True

    async def _run():
        return await engine._review_dimension_phase1(99, "style", "风格统一", "检查风格")

    result = asyncio.run(_run())
    assert result.get("skipped") is True
    assert result.get("reason") == "empty_content"
    cleanup([PROJ_NAME])
    return "空内容跳过 OK"


# ============ 10. _review_dimension_phase1 — mock LLM 返回内容 ============
def t10():
    engine, proj_dir = _make_engine()
    original_content = "第1章 觉醒\n\n" + "这是测试内容。" * 100  # 足够多的中文字
    _write_chapter(proj_dir, 1, original_content)
    engine.llm.has_valid_config = lambda role: True

    async def _mock_call(role, system, user):
        return "第1章 觉醒（修订）\n\n" + "这是修订后的测试内容。" * 100

    engine.llm.call = _mock_call

    async def _run():
        return await engine._review_dimension_phase1(1, "style", "风格统一", "检查风格")

    result = asyncio.run(_run())
    assert result.get("dim_key") == "style"
    assert result.get("dim_name") == "风格统一"
    assert "new_content" in result
    assert "修订" in result["new_content"]
    assert "content" in result
    assert result["content"] == original_content
    cleanup([PROJ_NAME])
    return "mock LLM 审校 OK"


# ============ 11. run_review — 空章节跳过 ============
def t11():
    engine, _ = _make_engine()
    # 无章节文件 → 空结果
    engine.llm.has_valid_config = lambda role: True

    async def _run():
        return await engine.run_review()

    result = asyncio.run(_run())
    assert result["cancelled"] is False
    assert result["results"] == {}
    # 状态应为 completed
    assert engine.state.data.get("review", {}).get("status") == "completed"
    cleanup([PROJ_NAME])
    return "空章节跳过 OK"


# ============ 12. run_review — mock LLM 完整流程 ============
def t12():
    engine, proj_dir = _make_engine()
    # 写入一章足够长的内容
    content = "第1章 觉醒\n\n" + "林轩走进了青云山，开始了他的修仙之路。" * 50
    _write_chapter(proj_dir, 1, content)
    engine.llm.has_valid_config = lambda role: True

    async def _mock_call(role, system, user):
        # 返回略微修改的内容（加一个字保证不缩水）
        return "第1章 觉醒\n\n" + "林轩走进了青云山，开始了他的修仙之路。" * 50 + "修订。"

    engine.llm.call = _mock_call

    async def _run():
        return await engine.run_review()

    result = asyncio.run(_run())
    assert result["cancelled"] is False
    # 应有审校结果
    assert len(result["results"]) > 0
    # 至少有一个维度的结果
    has_style = any("style" in k for k in result["results"].keys())
    assert has_style, f"应有 style 维度结果，实际 keys: {list(result['results'].keys())}"
    # 状态应为 completed
    assert engine.state.data.get("review", {}).get("status") == "completed"
    cleanup([PROJ_NAME])
    return f"完整审校 OK ({len(result['results'])} 个结果)"


# ============ 13. cancel 取消审校 ============
def t13():
    engine, proj_dir = _make_engine()
    _write_chapter(proj_dir, 1, "第1章 测试\n\n" + "内容。" * 100)
    engine.llm.has_valid_config = lambda role: True

    async def _mock_call(role, system, user):
        return "第1章 测试\n\n" + "内容。" * 100

    engine.llm.call = _mock_call
    engine.cancel()  # 设置取消标志

    async def _run():
        return await engine.run_review()

    result = asyncio.run(_run())
    assert result["cancelled"] is True
    # 状态应为 paused（取消后）
    assert engine.state.data.get("review", {}).get("status") == "paused"
    cleanup([PROJ_NAME])
    return "取消审校 OK"


# ============ 14. get_status 获取状态 ============
def t14():
    engine, _ = _make_engine()
    status = engine.get_status()
    assert "status" in status
    assert "current_chapter" in status
    assert "current_dimension" in status
    assert "dimensions_done" in status
    assert status["status"] == "pending"  # 初始状态
    assert status["current_chapter"] == 0
    assert status["current_dimension"] == 0
    assert status["dimensions_done"] == []

    # 修改状态后验证
    engine.state.review_set_status("running")
    engine._current_chapter = 3
    engine._current_dimension = 2
    status2 = engine.get_status()
    assert status2["status"] == "running"
    assert status2["current_chapter"] == 3
    assert status2["current_dimension"] == 2
    cleanup([PROJ_NAME])
    return "get_status OK"


if __name__ == '__main__':
    print("=" * 70)
    print("  审校引擎测试 (14 用例)")
    print("=" * 70)
    print()
    run("01. ReviewEngine 初始化", t01)
    run("02. 6 维度常量验证", t02)
    run("03. _get_all_chapters", t03)
    run("04. _get_chapter_summary", t04)
    run("05. _clean_chapter_content FS 清除", t05)
    run("06. _clean_chapter_content 标题统一", t06)
    run("07. _clean_chapter_content 空行压缩", t07)
    run("08. _review_dimension_phase1 无 LLM 跳过", t08)
    run("09. _review_dimension_phase1 空内容跳过", t09)
    run("10. _review_dimension_phase1 mock LLM", t10)
    run("11. run_review 空章节跳过", t11)
    run("12. run_review mock LLM 完整流程", t12)
    run("13. cancel 取消审校", t13)
    run("14. get_status 获取状态", t14)
    print()
    print("=" * 70)
    print(f"  结果:  {len(PASSED)} 通过 / {len(FAILED)} 失败")
    print("=" * 70)
    sys.exit(0 if not FAILED else 1)
