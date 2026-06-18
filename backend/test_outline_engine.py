"""大纲引擎测试 — 覆盖 OutlineEngine 初始化 / 占位大纲 / 章节解析 / 卷范围 / L2 头部 / MWR 决策 / 同步 DB。

LLM 调用全部 mock，文件系统测试用 create_project + cleanup。
"""
import sys
import os
import asyncio
import json
import shutil

sys.path.insert(0, '.')

from project_db import ProjectDB, create_project, delete_project, get_project_dir
from engines.outline.engine import OutlineEngine
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


PROJ_NAME = "test_outline"


def _make_engine(layer_max_rounds=1):
    """创建大纲引擎实例（无 LLM 配置）。"""
    cleanup([PROJ_NAME])
    create_project(PROJ_NAME, "测试大纲", "玄幻", 30)
    proj_dir = get_project_dir(PROJ_NAME)
    engine = OutlineEngine(
        proj_dir, PROJ_NAME,
        max_rounds_per_layer=layer_max_rounds,
        score_threshold=7.0,
        genre="",
    )
    # mock _ai_ingest_outline 避免依赖 KG 摄取逻辑
    async def _mock_ingest(layer, md_text):
        pass
    engine._ai_ingest_outline = _mock_ingest
    return engine, proj_dir


# ============ 1. OutlineEngine 初始化 ============
def t01():
    engine, proj_dir = _make_engine()
    assert engine.project_name == PROJ_NAME
    assert engine.project_dir == proj_dir
    assert engine.max_rounds_per_layer == 1
    assert engine.score_threshold == 7.0
    assert engine._current_layer == "L1"
    assert engine.requirements == ""
    assert engine._last_feedback == []
    cleanup([PROJ_NAME])
    return "初始化 OK"


# ============ 2. _placeholder_outline L1 ============
def t02():
    engine, _ = _make_engine()
    md = engine._placeholder_outline("L1")
    assert "L1 占位大纲" in md
    assert "基础信息栏" in md
    assert "世界观设定" in md
    assert "人物设定表" in md
    assert "分卷大纲" in md
    assert "结局规划" in md
    assert "FS-001" in md  # 伏笔编号
    cleanup([PROJ_NAME])
    return "L1 占位 OK"


# ============ 3. _placeholder_outline L2 ============
def t03():
    engine, _ = _make_engine()
    md = engine._placeholder_outline("L2")
    assert "L2 章节细纲占位" in md
    assert "阶段划分" in md
    assert "逐章细纲" in md
    assert "第1章" in md
    assert "核心目的" in md
    assert "FS-001" in md
    # 未知层返回空字符串
    assert engine._placeholder_outline("L3") == ""
    cleanup([PROJ_NAME])
    return "L2 占位 OK"


# ============ 4. _parse_chapter_count ============
def t04():
    engine, _ = _make_engine()
    assert engine._parse_chapter_count("30") == 30
    assert engine._parse_chapter_count("30章") == 30
    assert engine._parse_chapter_count("") == 0
    assert engine._parse_chapter_count(None) == 0
    assert engine._parse_chapter_count("约30章") == 30
    assert engine._parse_chapter_count("120-150") == 120  # 取第一个数字
    cleanup([PROJ_NAME])
    return "解析章节数 OK"


# ============ 5. _calc_volume_chapter_range ============
def t05():
    engine, _ = _make_engine()
    volumes = [
        {"卷号": 1, "卷名": "开篇", "卷总章节": "10"},
        {"卷号": 2, "卷名": "发展", "卷总章节": "20"},
        {"卷号": 3, "卷名": "高潮", "卷总章节": "15"},
    ]
    assert engine._calc_volume_chapter_range(volumes, 0) == (1, 10)
    assert engine._calc_volume_chapter_range(volumes, 1) == (11, 30)
    assert engine._calc_volume_chapter_range(volumes, 2) == (31, 45)
    # 空章节数返回 (0, 0)
    bad_vols = [{"卷号": 1, "卷名": "x", "卷总章节": ""}]
    assert engine._calc_volume_chapter_range(bad_vols, 0) == (0, 0)
    cleanup([PROJ_NAME])
    return "卷范围计算 OK"


# ============ 6. _build_l2_header ============
def t06():
    engine, _ = _make_engine()
    volumes = [
        {"卷号": 1, "卷名": "开篇", "卷总章节": "10", "卷核心主题": "起步"},
        {"卷号": 2, "卷名": "发展", "卷总章节": "20", "卷核心主题": "成长"},
    ]
    header = engine._build_l2_header(volumes)
    assert "章节细纲" in header
    assert "分卷概览" in header
    assert "第1卷" in header
    assert "开篇" in header
    assert "第2卷" in header
    assert "发展" in header
    assert "起步" in header
    assert "成长" in header
    cleanup([PROJ_NAME])
    return "L2 头部 OK"


# ============ 7. _extract_chapters_from_batch ============
def t07():
    engine, _ = _make_engine()
    batch_md = """一些介绍文字

### 第1章 开篇
- 内容

### 第2章 发展
- 内容
"""
    result = engine._extract_chapters_from_batch(batch_md, 1, 2)
    assert result.startswith("### 第1章")
    assert "第2章" in result
    # 无章节标记时返回原文
    no_chapter = "没有章节标记的内容"
    result2 = engine._extract_chapters_from_batch(no_chapter, 1, 2)
    assert result2 == no_chapter
    # 空字符串
    assert engine._extract_chapters_from_batch("", 1, 2) == ""
    cleanup([PROJ_NAME])
    return "批次提取 OK"


# ============ 8. _count_chapters_in_md ============
def t08():
    engine, _ = _make_engine()
    md = "### 第1章 x\n### 第2章 y\n### 第3章 z"
    assert engine._count_chapters_in_md(md) == 3
    assert engine._count_chapters_in_md("") == 0
    assert engine._count_chapters_in_md("没有章节") == 0
    assert engine._count_chapters_in_md("### 第10章 测试") == 1
    cleanup([PROJ_NAME])
    return "章节统计 OK"


# ============ 9. _extract_volumes_from_l1_md ============
def t09():
    engine, proj_dir = _make_engine()
    l1_md = """# L1 大纲

## 五、分卷大纲
### 第1卷 开篇
- 卷核心主题：起步
- 卷定位：开篇
- 卷总章节：30
- 卷内核心冲突：起步冲突

### 第2卷 发展
- 卷核心主题：成长
- 卷定位：成长
- 卷总章节：40
- 卷内核心冲突：发展冲突
"""
    with open(os.path.join(proj_dir, "outline_L1.md"), "w", encoding="utf-8") as f:
        f.write(l1_md)

    volumes = engine._extract_volumes_from_l1_md()
    assert len(volumes) == 2
    assert volumes[0]["卷号"] == 1
    assert volumes[0]["卷名"] == "开篇"
    assert volumes[0]["卷总章节"] == "30"
    assert volumes[0]["卷核心主题"] == "起步"
    assert volumes[1]["卷号"] == 2
    assert volumes[1]["卷总章节"] == "40"
    assert volumes[1]["卷内核心冲突"] == "发展冲突"

    # 无分卷信息返回空列表
    with open(os.path.join(proj_dir, "outline_L1.md"), "w", encoding="utf-8") as f:
        f.write("# 无分卷大纲")
    assert engine._extract_volumes_from_l1_md() == []
    cleanup([PROJ_NAME])
    return "L1 markdown 提取卷 OK"


# ============ 10. _get_l1_volumes 从 JSON 提取 ============
def t10():
    engine, proj_dir = _make_engine()
    l1_json = {
        "basic": {"作品名称": "测试"},
        "volumes": [
            {"卷号": 1, "卷名": "开篇", "卷总章节": "30", "卷核心主题": "起步"},
            {"卷号": 2, "卷名": "发展", "卷总章节": "40", "卷核心主题": "成长"},
        ]
    }
    with open(os.path.join(proj_dir, "outline_L1.json"), "w", encoding="utf-8") as f:
        json.dump(l1_json, f, ensure_ascii=False)

    volumes = engine._get_l1_volumes()
    assert len(volumes) == 2
    assert volumes[0]["卷号"] == 1
    assert volumes[1]["卷总章节"] == "40"

    # 无 volumes 字段返回空
    with open(os.path.join(proj_dir, "outline_L1.json"), "w", encoding="utf-8") as f:
        json.dump({"basic": {}}, f, ensure_ascii=False)
    assert engine._get_l1_volumes() == []

    # volumes 中无卷总章节返回空
    with open(os.path.join(proj_dir, "outline_L1.json"), "w", encoding="utf-8") as f:
        json.dump({"volumes": [{"卷号": 1, "卷名": "x"}]}, f, ensure_ascii=False)
    assert engine._get_l1_volumes() == []
    cleanup([PROJ_NAME])
    return "L1 JSON 提取卷 OK"


# ============ 11. _sync_chapters_to_db ============
def t11():
    engine, proj_dir = _make_engine()
    l2_md = """# 章节细纲

## 逐章细纲

### 第1章 觉醒
- 核心目的：主角登场

### 第2章 试炼
- 核心目的：实力提升

### 第3章 历练
- 核心目的：外出冒险
"""
    with open(os.path.join(proj_dir, "outline_L2.md"), "w", encoding="utf-8") as f:
        f.write(l2_md)

    engine._sync_chapters_to_db()

    db = ProjectDB(PROJ_NAME)
    info = db.get_project()
    db.close()
    # total_chapters 应被更新（至少 3 章）
    assert info.get("total_chapters", 0) >= 3, f"期望 >=3，实际 {info.get('total_chapters')}"
    # chapter_titles.json 应存在
    titles_path = os.path.join(proj_dir, "chapter_titles.json")
    assert os.path.isfile(titles_path)
    with open(titles_path, "r", encoding="utf-8") as f:
        titles = json.load(f)
    assert "1" in titles
    assert "觉醒" in titles["1"]
    assert "3" in titles
    assert "历练" in titles["3"]
    cleanup([PROJ_NAME])
    return "同步 DB OK"


# ============ 12. manager_decide 决定下一层 ============
def t12():
    engine, _ = _make_engine()
    # 初始状态：无已完成层 → 应返回 write L1
    task = engine.manager_decide(1, None)
    assert task.action == "write"
    assert task.layer == "L1"

    # 标记 L1 完成
    engine.state.outline_complete_layer("L1")
    task = engine.manager_decide(1, None)
    assert task.action == "write"
    assert task.layer == "L2"

    # 标记 L2 完成 → 应返回 review all
    engine.state.outline_complete_layer("L2")
    task = engine.manager_decide(1, None)
    assert task.action == "review"
    assert task.layer == "all"
    cleanup([PROJ_NAME])
    return "manager_decide OK"


# ============ 13. manager_decide polish 模式 ============
def t13():
    engine, _ = _make_engine()
    # 上一轮有问题 → polish
    last_result = ReviewResult(score=4.0, issues=["问题1", "问题2"], all_required_passed=False)
    task = engine.manager_decide(1, last_result)
    assert task.action == "polish"
    assert task.focus_issues == ["问题1", "问题2"]
    assert "问题1" in task.context
    cleanup([PROJ_NAME])
    return "polish 决策 OK"


# ============ 14. manager_final_decision ============
def t14():
    engine, _ = _make_engine()
    # 无轮次记录 → 不接受
    decision = engine.manager_final_decision()
    assert decision.accepted is False

    # 添加高评分轮次 → 接受
    engine.state.outline_add_round(1, "L1", 7.5, [])
    decision = engine.manager_final_decision()
    assert decision.accepted is True

    # 添加低评分轮次（覆盖最后一条）→ 不接受
    engine.state.outline_add_round(2, "L1", 5.0, ["问题"])
    decision = engine.manager_final_decision()
    assert decision.accepted is False
    cleanup([PROJ_NAME])
    return "final_decision OK"


# ============ 15. generate_layer L1 占位路径（无 LLM） ============
def t15():
    engine, proj_dir = _make_engine(layer_max_rounds=1)
    # 无 LLM 配置 → 使用占位内容
    engine.llm.has_valid_config = lambda role: False

    async def _run():
        return await engine.generate_layer("L1")

    result = asyncio.run(_run())
    assert result["layer"] == "L1"
    assert "score" in result
    assert "issues" in result
    assert "all_required_passed" in result
    # 验证文件已生成
    assert os.path.isfile(os.path.join(proj_dir, "outline_L1.md"))
    assert os.path.isfile(os.path.join(proj_dir, "outline_L1.json"))
    # L1 应被标记为完成
    assert "L1" in engine.state.data.get("outline", {}).get("completed_layers", [])
    cleanup([PROJ_NAME])
    return "generate_layer L1 占位 OK"


# ============ 16. generate_layer mock LLM ============
def t16():
    engine, proj_dir = _make_engine(layer_max_rounds=1)
    engine.llm.has_valid_config = lambda role: True

    call_count = [0]

    async def _mock_call(role, system, user):
        call_count[0] += 1
        if role == "writer":
            return engine._placeholder_outline("L1")
        elif role == "reviewer":
            return json.dumps({"score": 8.0, "issues": [], "suggestions": ["很好"]})
        return ""

    engine.llm.call = _mock_call

    async def _run():
        return await engine.generate_layer("L1")

    result = asyncio.run(_run())
    assert result["layer"] == "L1"
    assert call_count[0] > 0  # 至少调用了 writer
    # 验证文件已生成
    assert os.path.isfile(os.path.join(proj_dir, "outline_L1.md"))
    cleanup([PROJ_NAME])
    return f"generate_layer mock LLM OK (调用 {call_count[0]} 次)"


if __name__ == '__main__':
    print("=" * 70)
    print("  大纲引擎测试 (16 用例)")
    print("=" * 70)
    print()
    run("01. OutlineEngine 初始化", t01)
    run("02. _placeholder_outline L1", t02)
    run("03. _placeholder_outline L2", t03)
    run("04. _parse_chapter_count", t04)
    run("05. _calc_volume_chapter_range", t05)
    run("06. _build_l2_header", t06)
    run("07. _extract_chapters_from_batch", t07)
    run("08. _count_chapters_in_md", t08)
    run("09. _extract_volumes_from_l1_md", t09)
    run("10. _get_l1_volumes", t10)
    run("11. _sync_chapters_to_db", t11)
    run("12. manager_decide 下一层", t12)
    run("13. manager_decide polish", t13)
    run("14. manager_final_decision", t14)
    run("15. generate_layer L1 占位", t15)
    run("16. generate_layer mock LLM", t16)
    print()
    print("=" * 70)
    print(f"  结果:  {len(PASSED)} 通过 / {len(FAILED)} 失败")
    print("=" * 70)
    sys.exit(0 if not FAILED else 1)
