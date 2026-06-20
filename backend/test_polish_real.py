"""真实文本润色测试 — 使用真实LLM调用测试完整润色流程。

测试步骤：
1. 读取项目2的章节作为"原文"
2. 构造模拟审查反馈（含全局+局部问题）
3. 调用段落润色 _polish_chapter（全文输出+还原）
4. 调用全文润色 _polish_chapter_fulltext（情节漂移检测）
5. 调用 Reviewer 评审润色前后内容
6. 对比润色前后差异，输出报告
"""
import sys
import os
import asyncio
import re
import json
import time

sys.path.insert(0, '.')

import paths
from project_db import ProjectDB, get_project_dir
from engines.writing.engine import WritingEngine
from engines.common.base_engine import MWRTask, Draft, ReviewResult

# 使用项目2（有真实章节）
PROJ_ID = "2"


def load_engine():
    """加载已有项目的引擎，复用 engine_registry 的预设加载逻辑。"""
    proj_dir = get_project_dir(PROJ_ID)
    if not proj_dir or not os.path.exists(proj_dir):
        print(f"[ERROR] 项目 {PROJ_ID} 不存在")
        sys.exit(1)

    # 从数据库读取项目信息
    db = ProjectDB(PROJ_ID)
    proj = db.get_project()
    if not proj:
        print(f"[ERROR] 数据库中无项目 {PROJ_ID}")
        sys.exit(1)

    # 加载项目级预设（与 _get_project_presets 一致）
    project_presets = db.get_presets()

    # 加载全局预设（与 _get_global_presets 一致）
    global_presets = []
    config_path = paths.get_config_path()
    if os.path.isfile(config_path):
        with open(config_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        presets = data.get("presets", [])
        if isinstance(presets, list):
            global_presets = presets
        elif isinstance(presets, dict):
            global_presets = list(presets.values())

    print(f"[INFO] 项目预设角色: {list(project_presets.keys())}")
    print(f"[INFO] 全局预设数量: {len(global_presets)}")
    if global_presets:
        print(f"[INFO] 全局预设名称: {[p.get('name', '?') for p in global_presets]}")

    engine = WritingEngine(
        proj_dir, PROJ_ID,
        project_presets=project_presets,
        global_presets=global_presets,
        total_chapters=proj.get("total_chapters", 120),
        max_polish_rounds=4,
        score_threshold=7.0,
        genre=proj.get("genre", ""),
    )
    return engine


def read_chapter(engine, ch):
    """读取章节内容"""
    path = engine._chapter_path(ch)
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    return None


def count_metrics(content):
    """统计文本指标"""
    cn_chars = len(re.findall(r'[\u4e00-\u9fff]', content))
    ellipsis = len(re.findall(r'……', content))
    said_count = len(re.findall(r'说道', content))
    paragraphs = [p for p in content.split("\n\n") if p.strip()]
    return {
        "cn_chars": cn_chars,
        "ellipsis": ellipsis,
        "said_count": said_count,
        "paragraphs": len(paragraphs),
    }


def print_metrics(label, metrics):
    """打印指标"""
    print(f"  {label}: {metrics['cn_chars']}字, {metrics['ellipsis']}个省略号, "
          f"{metrics['said_count']}个'说道', {metrics['paragraphs']}段")


async def test_polish_with_real_llm():
    """使用真实LLM测试润色"""
    print("=" * 70)
    print("  真实文本润色测试")
    print("=" * 70)

    engine = load_engine()

    # 检查LLM配置
    if not engine.llm.has_valid_config("writer"):
        print("[ERROR] Writer LLM未配置，无法测试")
        return
    if not engine.llm.has_valid_config("reviewer"):
        print("[ERROR] Reviewer LLM未配置，无法测试")
        return
    print("[OK] LLM配置有效")

    # 读取第99章
    ch = 99
    original = read_chapter(engine, ch)
    if not original:
        print(f"[ERROR] 第{ch}章不存在")
        return

    orig_metrics = count_metrics(original)
    print(f"\n[原文] 第{ch}章")
    print_metrics("指标", orig_metrics)
    print(f"  前100字: {original[:100]}...")

    # ========== 测试1: Reviewer 评审原文 ==========
    print(f"\n{'='*50}")
    print("测试1: Reviewer 评审原文")
    print(f"{'='*50}")

    draft = Draft(content=original, chapter_num=ch)
    review_result = await engine.reviewer_evaluate(draft)

    print(f"  评分: {review_result.score}/10")
    print(f"  all_required_passed: {review_result.all_required_passed}")
    print(f"  问题 ({len(review_result.issues)}):")
    for iss in review_result.issues[:8]:
        print(f"    - {iss}")
    if len(review_result.issues) > 8:
        print(f"    ... 还有{len(review_result.issues)-8}个问题")

    # ========== 测试2: 后处理流水线 ==========
    print(f"\n{'='*50}")
    print("测试2: 后处理流水线（_post_process）")
    print(f"{'='*50}")

    processed = engine._post_process(original)
    proc_metrics = count_metrics(processed)
    print_metrics("原文", orig_metrics)
    print_metrics("处理后", proc_metrics)

    ellipsis_diff = orig_metrics["ellipsis"] - proc_metrics["ellipsis"]
    said_diff = orig_metrics["said_count"] - proc_metrics["said_count"]
    print(f"  省略号减少: {ellipsis_diff}个")
    print(f"  '说道'减少: {said_diff}个")

    # 检查AI高频短语
    ai_phrases_found = []
    for phrase in engine._AI_PHRASE_BLACKLIST:
        if phrase in processed:
            ai_phrases_found.append(phrase)
    if ai_phrases_found:
        print(f"  [WARNING] 仍有AI短语: {ai_phrases_found}")
    else:
        print(f"  [OK] 无AI高频短语")

    # ========== 测试3: 段落润色（全文输出+还原） ==========
    print(f"\n{'='*50}")
    print("测试3: 段落润色（全文输出+还原非问题段落）")
    print(f"{'='*50}")

    # 构造模拟审查反馈
    test_issues = [
        "[局部][P1] 衔接断裂：开头场景与前章衔接不够自然",
        "[局部][P3] 对话标签重复：'说道'使用过多",
    ]
    task = MWRTask(
        action="polish",
        chapter_num=ch,
        focus_issues=test_issues,
        context="审查反馈：需要修复衔接和对话标签问题",
    )

    t0 = time.time()
    polish_result = await engine._polish_chapter(ch, task)
    elapsed = time.time() - t0

    polished = polish_result.content
    polish_metrics = count_metrics(polished)
    print(f"  耗时: {elapsed:.1f}s")
    print_metrics("润色后", polish_metrics)

    # 检查非问题段落是否被保留
    orig_paras = [p.strip() for p in original.split("\n\n") if p.strip()]
    polished_paras = [p.strip() for p in polished.split("\n\n") if p.strip()]

    # P1和P3是问题段落，其他应保留
    preserved_count = 0
    changed_count = 0
    for i, (op, pp) in enumerate(zip(orig_paras, polished_paras)):
        para_num = i + 1
        if para_num in {1, 3}:  # 问题段落
            if op != pp:
                changed_count += 1
                print(f"  P{para_num} 已修改 (前50字: {pp[:50]}...)")
            else:
                print(f"  P{para_num} 未修改 (LLM可能认为无需改)")
        else:
            if op == pp:
                preserved_count += 1
            else:
                print(f"  [WARNING] P{para_num} 非问题段落被修改了!")

    print(f"  非问题段落保留: {preserved_count}/{len(orig_paras)-2}")
    print(f"  问题段落修改: {changed_count}/2")

    # ========== 测试4: 全文润色（情节漂移检测） ==========
    print(f"\n{'='*50}")
    print("测试4: 全文润色（情节漂移检测）")
    print(f"{'='*50}")

    global_issues = [
        "[全局] AI痕迹明显：重复句式和疲劳词",
        "[全局] 省略号过多",
    ]
    task_fulltext = MWRTask(
        action="polish_fulltext",
        chapter_num=ch,
        focus_issues=global_issues,
        context="审查反馈：需要消除AI痕迹",
    )

    t0 = time.time()
    fulltext_result = await engine._polish_chapter_fulltext(ch, task_fulltext)
    elapsed = time.time() - t0

    fulltext_polished = fulltext_result.content
    fulltext_metrics = count_metrics(fulltext_polished)
    print(f"  耗时: {elapsed:.1f}s")
    print_metrics("全文润色后", fulltext_metrics)

    # 检查字数是否缩水
    char_ratio = fulltext_metrics["cn_chars"] / max(orig_metrics["cn_chars"], 1)
    print(f"  字数比例: {char_ratio:.1%}")
    if char_ratio < 0.7:
        print(f"  [WARNING] 字数缩水超过30%!")
    else:
        print(f"  [OK] 字数保持良好")

    # ========== 测试5: Reviewer 评审润色后内容 ==========
    print(f"\n{'='*50}")
    print("测试5: Reviewer 评审润色后内容")
    print(f"{'='*50}")

    # 用后处理后的内容评审
    polished_draft = Draft(content=processed, chapter_num=ch)
    polished_review = await engine.reviewer_evaluate(polished_draft)

    print(f"  原文评分: {review_result.score}/10")
    print(f"  润色后评分: {polished_review.score}/10")
    score_diff = polished_review.score - review_result.score
    if score_diff > 0:
        print(f"  [OK] 评分提升 +{score_diff:.1f}")
    elif score_diff == 0:
        print(f"  [INFO] 评分不变")
    else:
        print(f"  [WARNING] 评分下降 {score_diff:.1f}")

    print(f"  润色后问题 ({len(polished_review.issues)}):")
    for iss in polished_review.issues[:5]:
        print(f"    - {iss}")

    # ========== 总结 ==========
    print(f"\n{'='*70}")
    print("  测试总结")
    print(f"{'='*70}")
    print(f"  原文: {orig_metrics['cn_chars']}字, {orig_metrics['ellipsis']}个省略号, "
          f"{orig_metrics['said_count']}个'说道'")
    print(f"  后处理: {proc_metrics['cn_chars']}字, {proc_metrics['ellipsis']}个省略号, "
          f"{proc_metrics['said_count']}个'说道'")
    print(f"  评分: {review_result.score} → {polished_review.score} (差: {score_diff:+.1f})")
    print(f"  段落润色: 非问题段落保留{preserved_count}/{len(orig_paras)-2}")
    print(f"  全文润色: 字数比例{char_ratio:.1%}")


if __name__ == '__main__':
    asyncio.run(test_polish_with_real_llm())
