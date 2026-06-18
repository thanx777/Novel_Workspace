"""反幻觉测试 — 覆盖 CharacterTracker / PlotThreadTracker / ConsistencyChecker / FormatValidator / HallucinationGuardAdapter。

无 LLM 调用，全部本地逻辑测试。
"""
import sys
import os

sys.path.insert(0, '.')

from engines.common.hallucination_guard import (
    CharacterTracker, CharacterState,
    PlotThreadTracker, PlotThread,
    ConsistencyChecker,
    FormatValidator,
    HallucinationGuardAdapter,
)

PASSED, FAILED = [], []


def run(name, fn):
    try:
        r = fn()
        PASSED.append((name, r))
        print(f"  ✅ {name}")
    except Exception as e:
        FAILED.append((name, str(e)))
        print(f"  ❌ {name} → {e}")


# ============ 1. CharacterTracker — 添加和查询角色 ============
def t01():
    tracker = CharacterTracker()
    tracker.parse_memory("林轩：天剑宗弟子，位于青云山")
    assert "林轩" in tracker.characters
    char = tracker.characters["林轩"]
    assert char.name == "林轩"
    assert "天剑宗弟子" in char.notes
    assert char.location == "青云山"
    return "添加角色 OK"


# ============ 2. CharacterTracker — 别名解析 ============
def t02():
    tracker = CharacterTracker()
    tracker.parse_memory("林轩（小林子）：主角，少年")
    assert "林轩" in tracker.characters
    char = tracker.characters["林轩"]
    assert "小林子" in char.aliases, f"应记录别名，实际 {char.aliases}"
    return "别名解析 OK"


# ============ 3. CharacterTracker — 检测未注册角色（get_context_block） ============
def t03():
    tracker = CharacterTracker()
    # 空时返回空字符串
    assert tracker.get_context_block(1) == ""
    # 添加角色
    tracker.parse_memory("林轩：主角")
    tracker.parse_memory("苏清歌：女主")
    ctx = tracker.get_context_block(1)
    assert "林轩" in ctx
    assert "苏清歌" in ctx
    assert "角色状态速查" in ctx
    return "上下文块 OK"


# ============ 4. CharacterTracker — update_from_chapter 更新章节 ============
def t04():
    tracker = CharacterTracker()
    tracker.update_from_chapter("林轩走进了青云山。", chapter_num=5, known_names=["林轩", "苏清歌"])
    assert "林轩" in tracker.characters
    assert tracker.characters["林轩"].last_chapter == 5
    # 苏清歌未在文本中出现，不应被添加
    assert "苏清歌" not in tracker.characters
    return "update_from_chapter OK"


# ============ 5. CharacterTracker — merge_memory_update 更新 last_chapter ============
def t05():
    tracker = CharacterTracker()
    tracker.parse_memory("林轩：主角")
    tracker.merge_memory_update("林轩再次出现", chapter_num=8)
    assert tracker.characters["林轩"].last_chapter == 8
    return "merge_memory_update OK"


# ============ 6. PlotThreadTracker — 添加剧情线 ============
def t06():
    tracker = PlotThreadTracker()
    tid = tracker.add_thread("灭门真相", "conflict", "主角调查家族被灭", chapter=1)
    assert tid.startswith("thread_")
    assert tid in tracker.threads
    thread = tracker.threads[tid]
    assert thread.name == "灭门真相"
    assert thread.type == "conflict"
    assert thread.status == "open"
    assert thread.introduced_chapter == 1
    return "添加剧情线 OK"


# ============ 7. PlotThreadTracker — resolve_thread 标记解决 ============
def t07():
    tracker = PlotThreadTracker()
    tid = tracker.add_thread("神秘玉佩", "foreshadowing", "玉佩的秘密", chapter=1)
    tracker.resolve_thread(tid, chapter=20)
    thread = tracker.threads[tid]
    assert thread.status == "resolved"
    assert thread.resolved_chapter == 20
    # get_open_threads 不应包含已解决的
    open_threads = tracker.get_open_threads()
    assert len(open_threads) == 0
    return "resolve_thread OK"


# ============ 8. PlotThreadTracker — get_open_threads 检测断裂 ============
def t08():
    tracker = PlotThreadTracker()
    tracker.add_thread("线索1", "foreshadowing", "描述1", chapter=1)
    tracker.add_thread("线索2", "mystery", "描述2", chapter=2)
    tracker.add_thread("线索3", "conflict", "描述3", chapter=3)
    open_threads = tracker.get_open_threads()
    assert len(open_threads) == 3
    # 解决一个
    tracker.resolve_thread("thread_1", chapter=10)
    open_threads = tracker.get_open_threads()
    assert len(open_threads) == 2
    return "断裂检测 OK"


# ============ 9. PlotThreadTracker — get_context_block 格式化 ============
def t09():
    tracker = PlotThreadTracker()
    # 空时返回空字符串
    assert tracker.get_context_block() == ""
    tracker.add_thread("伏笔1", "foreshadowing", "重要伏笔", chapter=1)
    ctx = tracker.get_context_block()
    assert "待回收伏笔" in ctx
    assert "伏笔1" in ctx
    assert "重要伏笔" in ctx
    assert "第1章" in ctx
    return "上下文格式化 OK"


# ============ 10. PlotThreadTracker — parse_from_memory 从记忆提取 ============
def t10():
    tracker = PlotThreadTracker()
    memory = """
伏笔：神秘玉佩的秘密
待回收：主角的家族血统
未解决：与反派的最终对决
悬念：黑衣人的身份
"""
    tracker.parse_from_memory(memory, chapter_num=5)
    open_threads = tracker.get_open_threads()
    assert len(open_threads) >= 4, f"应至少提取 4 条线索，实际 {len(open_threads)}"
    return f"提取 {len(open_threads)} 条线索"


# ============ 11. ConsistencyChecker — check_format_issues 检测 AI 痕迹 ============
def t11():
    checker = ConsistencyChecker()
    # 正常文本不应有问题
    issues = checker.check_format_issues("这是一段正常的小说内容，没有AI痕迹。")
    assert issues == []
    # 包含多次 AI 句式
    text = "不可否认，这是好的。不可否认，那是坏的。不可否认，都很棒。"
    issues = checker.check_format_issues(text)
    assert len(issues) > 0
    assert any("AI" in i for i in issues)
    return f"检测到 {len(issues)} 个 AI 痕迹"


# ============ 12. ConsistencyChecker — check_name_consistency 检测错字 ============
def t12():
    checker = ConsistencyChecker()
    # 名字 "林轩之" 错写成 "林轩"（去掉一个字）
    text = "林轩走进了房间。"  # 缺少"之"
    issues = checker.check_name_consistency(text, known_names=["林轩之"])
    # 应检测到疑似错字（因为 "林轩之" 长度>=3，去掉一个字得到 "林轩" 在文中出现）
    assert len(issues) > 0, "应检测到疑似人名错字"
    assert "林轩之" in issues[0]
    return "错字检测 OK"


# ============ 13. ConsistencyChecker — build_check_prompt 构建 prompt ============
def t13():
    checker = ConsistencyChecker()
    prompt = checker.build_check_prompt(
        chapter_content="这是章节内容。",
        chapter_num=5,
        outline="第5章：测试章节",
        character_context="角色A：主角",
        prev_chapter_end="上一章结尾。",
    )
    assert "第5章" in prompt
    assert "这是章节内容" in prompt
    assert "测试章节" in prompt
    assert "角色A" in prompt
    assert "上一章结尾" in prompt
    assert "通过" in prompt or "需修改" in prompt
    return "build_check_prompt OK"


# ============ 14. ConsistencyChecker — _extract_outline_section 提取大纲段 ============
def t14():
    checker = ConsistencyChecker()
    outline = """
第1章 开篇
第2章 觉醒
第3章 试炼
"""
    section = checker._extract_outline_section(outline, 2)
    assert "觉醒" in section
    # 不存在的章节
    section = checker._extract_outline_section(outline, 99)
    assert section == ""
    return "大纲段提取 OK"


# ============ 15. FormatValidator — count_chinese_chars 统计中文字数 ============
def t15():
    assert FormatValidator.count_chinese_chars("hello world") == 0
    assert FormatValidator.count_chinese_chars("你好世界") == 4
    assert FormatValidator.count_chinese_chars("hello 你好 world 世界") == 4
    assert FormatValidator.count_chinese_chars("") == 0
    return "中文字数统计 OK"


# ============ 16. FormatValidator — has_chapter_title 章节标题检测 ============
def t16():
    # 有标题（数字格式）
    ok, _ = FormatValidator.has_chapter_title("第1章 开篇\n正文...")
    assert ok is True
    ok, _ = FormatValidator.has_chapter_title("第1节 开篇\n正文...")
    assert ok is True
    ok, _ = FormatValidator.has_chapter_title("Chapter 1: Beginning")
    assert ok is True
    ok, _ = FormatValidator.has_chapter_title("# 第1章 开篇\n正文...")
    assert ok is True
    # 无标题
    ok, msg = FormatValidator.has_chapter_title("这是没有标题的章节内容。")
    assert ok is False
    # 指定章号
    ok, _ = FormatValidator.has_chapter_title("第5章 测试", expected_num=5)
    assert ok is True
    # 注意：源码实现仅支持 \d+ 数字格式，不支持中文数字"第一章"
    return "章节标题检测 OK"


# ============ 17. FormatValidator — validate 字数不足检测 ============
def t17():
    v = FormatValidator()
    # 字数不足
    content = "第1章 测试\n\n短内容。"
    ok, issues = v.validate(content, chapter_num=1)
    assert ok is False
    assert any("字数不足" in i for i in issues)
    return "字数不足检测 OK"


# ============ 18. FormatValidator — validate 占位符检测 ============
def t18():
    v = FormatValidator()
    # 包含占位符
    long_content = "第1章 测试\n\n" + "这是测试内容。" * 200 + "[TODO]"
    ok, issues = v.validate(long_content, chapter_num=1)
    assert ok is False
    assert any("占位符" in i for i in issues)
    return "占位符检测 OK"


# ============ 19. FormatValidator — validate 空内容检测 ============
def t19():
    v = FormatValidator()
    ok, issues = v.validate("", chapter_num=1)
    assert ok is False
    # 空内容应有多个问题
    assert len(issues) > 0
    return "空内容检测 OK"


# ============ 20. FormatValidator — validate_with_quality 质量评分 ============
def t20():
    v = FormatValidator()
    # 合规内容
    content = "第1章 测试\n\n" + "这是测试内容。" * 200 + "\n\n" + '"你好。"他说道。' * 3
    result = v.validate_with_quality(content, chapter_num=1)
    assert "passed" in result
    assert "issues" in result
    assert "char_count" in result
    assert "paragraph_count" in result
    assert "has_title" in result
    assert "quality_score" in result
    assert result["char_count"] >= 1000
    assert result["has_title"] is True
    assert 0 <= result["quality_score"] <= 100
    return f"质量评分 {result['quality_score']}"


# ============ 21. HallucinationGuardAdapter — 集成入口初始化 ============
def t21():
    adapter = HallucinationGuardAdapter(word_count_min=3000, word_count_max=5000)
    assert adapter.tracker is not None
    assert adapter.plot_tracker is not None
    assert adapter.consistency is not None
    assert adapter.validator is not None
    # 验证字数配置传递给 validator
    assert adapter.validator.ideal_min_words == 3000
    assert adapter.validator.ideal_max_words == 5000
    return "集成入口初始化 OK"


# ============ 22. HallucinationGuardAdapter — update_memory 集成更新 ============
def t22():
    adapter = HallucinationGuardAdapter()
    memory = """
林轩：天剑宗弟子
伏笔：神秘玉佩的秘密
"""
    adapter.update_memory(memory, chapter_num=1)
    # 角色应被添加
    assert "林轩" in adapter.tracker.characters
    # 伏笔应被添加
    open_threads = adapter.plot_tracker.get_open_threads()
    assert len(open_threads) >= 1
    return "update_memory 集成 OK"


# ============ 23. HallucinationGuardAdapter — get_writing_context 获取写作上下文 ============
def t23():
    adapter = HallucinationGuardAdapter()
    # 空时返回空字符串
    assert adapter.get_writing_context(1) == ""
    # 添加角色和伏笔
    adapter.update_memory("林轩：主角\n伏笔：神秘玉佩", chapter_num=1)
    ctx = adapter.get_writing_context(2)
    assert "林轩" in ctx
    assert "神秘玉佩" in ctx
    return "get_writing_context OK"


# ============ 24. HallucinationGuardAdapter — validate_chapter 校验章节 ============
def t24():
    adapter = HallucinationGuardAdapter()
    content = "第1章 测试\n\n" + "这是测试内容。" * 200
    result = adapter.validate_chapter(content, chapter_num=1)
    assert "passed" in result
    assert "quality_score" in result
    return "validate_chapter OK"


# ============ 25. HallucinationGuardAdapter — quick_local_check 快速本地检查 ============
def t25():
    adapter = HallucinationGuardAdapter()
    # 正常文本
    issues = adapter.quick_local_check("这是一段正常的小说内容。", known_names=["林轩"])
    assert isinstance(issues, list)
    # 包含 AI 痕迹
    text = "不可否认，这是好的。不可否认，那是坏的。不可否认，都很棒。"
    issues = adapter.quick_local_check(text)
    assert len(issues) > 0
    return "quick_local_check OK"


# ============ 26. HallucinationGuardAdapter — get_open_plot_threads ============
def t26():
    adapter = HallucinationGuardAdapter()
    adapter.update_memory("伏笔：神秘玉佩\n悬念：黑衣人身份", chapter_num=1)
    threads = adapter.get_open_plot_threads()
    assert isinstance(threads, list)
    assert len(threads) >= 2
    for t in threads:
        assert "name" in t
        assert "type" in t
        assert "description" in t
        assert "introduced_chapter" in t
    return f"获取 {len(threads)} 条开放线索"


# ============ 27. HallucinationGuardAdapter — build_consistency_check_prompt ============
def t27():
    adapter = HallucinationGuardAdapter()
    adapter.update_memory("林轩：主角", chapter_num=1)
    prompt = adapter.build_consistency_check_prompt(
        chapter_content="章节内容",
        chapter_num=5,
        outline="第5章 测试",
        prev_chapter_end="上一章结尾",
    )
    assert "第5章" in prompt
    assert "章节内容" in prompt
    assert "林轩" in prompt  # 角色上下文应被注入
    return "build_consistency_check_prompt OK"


if __name__ == '__main__':
    print("=" * 70)
    print("  反幻觉测试 (27 用例)")
    print("=" * 70)
    print()
    run("01. CharacterTracker 添加查询角色", t01)
    run("02. CharacterTracker 别名解析", t02)
    run("03. CharacterTracker 上下文块", t03)
    run("04. CharacterTracker update_from_chapter", t04)
    run("05. CharacterTracker merge_memory_update", t05)
    run("06. PlotThreadTracker 添加剧情线", t06)
    run("07. PlotThreadTracker resolve_thread", t07)
    run("08. PlotThreadTracker get_open_threads", t08)
    run("09. PlotThreadTracker 上下文格式化", t09)
    run("10. PlotThreadTracker parse_from_memory", t10)
    run("11. ConsistencyChecker AI 痕迹检测", t11)
    run("12. ConsistencyChecker 人名错字检测", t12)
    run("13. ConsistencyChecker build_check_prompt", t13)
    run("14. ConsistencyChecker 大纲段提取", t14)
    run("15. FormatValidator 中文字数统计", t15)
    run("16. FormatValidator 章节标题检测", t16)
    run("17. FormatValidator 字数不足检测", t17)
    run("18. FormatValidator 占位符检测", t18)
    run("19. FormatValidator 空内容检测", t19)
    run("20. FormatValidator 质量评分", t20)
    run("21. HallucinationGuardAdapter 初始化", t21)
    run("22. HallucinationGuardAdapter update_memory", t22)
    run("23. HallucinationGuardAdapter get_writing_context", t23)
    run("24. HallucinationGuardAdapter validate_chapter", t24)
    run("25. HallucinationGuardAdapter quick_local_check", t25)
    run("26. HallucinationGuardAdapter get_open_plot_threads", t26)
    run("27. HallucinationGuardAdapter build_consistency_check_prompt", t27)
    print()
    print("=" * 70)
    print(f"  结果:  {len(PASSED)} 通过 / {len(FAILED)} 失败")
    print("=" * 70)
    sys.exit(0 if not FAILED else 1)
