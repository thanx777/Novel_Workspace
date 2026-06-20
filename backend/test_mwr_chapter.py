"""对已有章节运行 MWR 润色循环（跳过首轮写入，直接从 Review 开始）。

用法: python test_mwr_chapter.py [章节号]
默认: 第50章
"""
import sys
import os
import asyncio
import json
import time
import re

sys.path.insert(0, '.')

import paths
from project_db import ProjectDB, get_project_dir
from engines.writing.engine import WritingEngine
from engines.common.base_engine import MWRTask, Draft, ReviewResult

PROJ_ID = "2"


def load_engine():
    """加载引擎"""
    proj_dir = get_project_dir(PROJ_ID)
    db = ProjectDB(PROJ_ID)
    proj = db.get_project()
    if not proj:
        print(f"[ERROR] 数据库中无项目 {PROJ_ID}")
        sys.exit(1)

    project_presets = db.get_presets()

    global_presets = []
    config_path = paths.get_config_path()
    if os.path.isfile(config_path):
        with open(config_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        presets = data.get("presets", [])
        global_presets = presets if isinstance(presets, list) else list(presets.values())

    print(f"[INFO] 项目预设角色: {list(project_presets.keys())}")
    print(f"[INFO] 全局预设: {[p.get('name', '?') for p in global_presets]}")

    logs = []

    def yield_func(data):
        logs.append(data)
        status = data.get("status", "")
        if status == "mwr_round":
            print(f"\n{'='*60}")
            print(f"  MWR 第 {data['round']} 轮 / 上限 {data['max_rounds']}")
            print(f"{'='*60}")
        elif status == "manager_decided":
            action = data.get("action", "?")
            print(f"  [Manager] 决策: {action}")
        elif status == "writer_done":
            print(f"  [Writer] 完成")
        elif status == "reviewer_done":
            score = data.get("score", 0)
            issues = data.get("issues", [])
            passed = data.get("all_required_passed", False)
            print(f"  [Reviewer] 评分: {score}/10, 硬性校验: {'通过' if passed else '未通过'}")
            for iss in issues[:5]:
                print(f"    - {iss}")
            if len(issues) > 5:
                print(f"    ... 还有{len(issues)-5}个问题")
        elif status == "info":
            print(f"  [Info] {data.get('message', '')}")
        elif status == "warning":
            print(f"  [Warning] {data.get('message', '')}")
        elif status in ("cycle_completed", "cycle_ended", "cycle_max_rounds", "cycle_stuck"):
            print(f"\n  *** {data.get('reason', status)} ***")

    engine = WritingEngine(
        proj_dir, PROJ_ID,
        project_presets=project_presets,
        global_presets=global_presets,
        yield_func=yield_func,
        total_chapters=proj.get("total_chapters", 120),
        max_polish_rounds=4,
        score_threshold=7.0,
        genre=proj.get("genre", ""),
    )
    return engine, logs


def count_metrics(content):
    cn_chars = len(re.findall(r'[\u4e00-\u9fff]', content))
    ellipsis = len(re.findall(r'……', content))
    said_count = len(re.findall(r'说道', content))
    ai_phrases = ["心中一震", "不禁感叹", "与此同时", "值得注意的是", "综上所述",
                  "由此可见", "颇为", "甚是", "不禁", "心中暗道",
                  "嘴角微微上扬", "眼中闪过一丝", "沉默了片刻", "深吸了一口气"]
    ai_found = [p for p in ai_phrases if p in content]
    paragraphs = [p for p in content.split("\n\n") if p.strip()]
    return {
        "cn_chars": cn_chars,
        "ellipsis": ellipsis,
        "said_count": said_count,
        "ai_phrases": ai_found,
        "paragraphs": len(paragraphs),
    }


def print_metrics(label, m):
    ai_str = f", AI短语: {m['ai_phrases']}" if m['ai_phrases'] else ", 无AI短语"
    print(f"  {label}: {m['cn_chars']}字, {m['ellipsis']}个省略号, "
          f"{m['said_count']}个'说道'{ai_str}, {m['paragraphs']}段")


async def run_mwr_polish(chapter_num):
    """对已有章节运行 MWR 润色循环（跳过首轮写入）"""
    engine, logs = load_engine()

    # 读取原文
    original = engine._read_chapter(chapter_num)
    if not original:
        print(f"[ERROR] 第{chapter_num}章不存在")
        return

    orig_metrics = count_metrics(original)
    print(f"\n{'='*70}")
    print(f"  对第{chapter_num}章运行 MWR 润色循环")
    print(f"{'='*70}")
    print_metrics("原文指标", orig_metrics)
    print(f"  原文前150字: {original[:150]}...")

    # 手动跑 MWR 循环，跳过首轮写入
    engine._current_chapter = chapter_num
    engine._polish_count = 0
    engine._rewrite_count = 0
    engine._last_valid_ai_score = None
    engine._previous_issues = set()
    engine._ineffective_polish_count = 0

    max_rounds = engine.mode_config.get("max_rounds_writing", 10)
    score_threshold = engine.score_threshold

    # 第1轮：直接 Review 已有章节（跳过写入）
    print(f"\n{'='*60}")
    print(f"  R1: Review 原文（跳过写入）")
    print(f"{'='*60}")

    draft = Draft(content=original, chapter_num=chapter_num)
    first_review = await engine.reviewer_evaluate(draft)
    engine._emit({
        "status": "reviewer_done", "round": 1,
        "score": first_review.score, "issues": first_review.issues,
        "all_required_passed": first_review.all_required_passed,
    })

    last_result = first_review
    round_num = 1

    # 如果首轮就通过，直接结束
    if first_review.score >= score_threshold and first_review.all_required_passed:
        print(f"\n  *** 首轮评分 {first_review.score} 已达标 ***")
    else:
        # 后续轮次：Manager 决策 → Writer 执行 → Reviewer 评审
        while True:
            round_num += 1
            if round_num > max_rounds:
                engine._emit({"status": "cycle_max_rounds", "round": round_num,
                              "reason": f"达到轮次上限({max_rounds})"})
                break

            engine._emit({"status": "mwr_round", "round": round_num, "max_rounds": max_rounds})

            # Manager 决策
            task = engine.manager_decide(round_num, last_result)
            engine._emit({"status": "manager_decided", "round": round_num, "action": task.action})

            if task.action == "accept_current":
                engine._emit({"status": "cycle_ended", "reason": "润色次数用尽，接受当前内容"})
                break

            # Writer 执行
            draft = await engine.writer_execute(task)
            engine._emit({"status": "writer_done", "round": round_num})

            # 后处理
            if draft.content:
                draft.content = engine._post_process(draft.content)
                draft.content = engine._deduplicate_paragraphs(draft.content)
                engine._write_atomic(engine._chapter_path(chapter_num), draft.content)

            # Reviewer 评审
            result = await engine.reviewer_evaluate(draft)
            last_result = result
            engine._emit({
                "status": "reviewer_done", "round": round_num,
                "score": result.score, "issues": result.issues,
                "all_required_passed": result.all_required_passed,
            })

            # 评分波动保护
            if engine._last_valid_ai_score is not None and result.score < engine._last_valid_ai_score:
                result.score = engine._last_valid_ai_score
                print(f"  [评分保护] 润色后评分低于上次，取较高分 {result.score}")
            engine._last_valid_ai_score = result.score

            # 通过判断
            if result.score >= score_threshold and result.all_required_passed:
                engine._emit({"status": "cycle_completed", "round": round_num, "score": result.score})
                break

    # 读取最终内容
    final_content = engine._read_chapter(chapter_num) or original
    final_metrics = count_metrics(final_content)

    # 输出报告
    print(f"\n{'='*70}")
    print(f"  MWR 润色循环报告")
    print(f"{'='*70}")
    print_metrics("原文", orig_metrics)
    print_metrics("结果", final_metrics)
    print(f"  字数变化: {orig_metrics['cn_chars']} → {final_metrics['cn_chars']} "
          f"({final_metrics['cn_chars'] - orig_metrics['cn_chars']:+d})")
    print(f"  省略号变化: {orig_metrics['ellipsis']} → {final_metrics['ellipsis']} "
          f"({final_metrics['ellipsis'] - orig_metrics['ellipsis']:+d})")

    # 各轮评分
    print(f"\n  各轮评分:")
    for log in logs:
        if log.get("status") == "reviewer_done":
            round_n = log.get("round", "?")
            score = log.get("score", 0)
            passed = log.get("all_required_passed", False)
            issues_count = len(log.get("issues", []))
            print(f"    R{round_n}: {score}/10 (硬性: {'通过' if passed else '未通过'}, {issues_count}个问题)")

    # Manager 决策序列
    print(f"\n  Manager 决策序列:")
    for log in logs:
        if log.get("status") == "manager_decided":
            round_n = log.get("round", "?")
            action = log.get("action", "?")
            print(f"    R{round_n}: {action}")

    # 效果判定
    print(f"\n{'='*70}")
    print(f"  效果判定")
    print(f"{'='*70}")
    final_score = last_result.score if last_result else 0
    if final_score >= 7.0:
        print(f"  [PASS] 评分 {final_score} >= 7.0")
    elif final_score >= 5.0:
        print(f"  [PARTIAL] 评分 {final_score}，有提升但未达标")
    else:
        print(f"  [FAIL] 评分 {final_score}，润色未有效提升")

    ellipsis_ok = final_metrics["ellipsis"] <= 5
    ai_ok = len(final_metrics["ai_phrases"]) == 0
    print(f"  省略号: {'PASS' if ellipsis_ok else 'FAIL'} ({final_metrics['ellipsis']}个)")
    print(f"  AI短语: {'PASS' if ai_ok else 'FAIL'} ({final_metrics['ai_phrases']})")


if __name__ == '__main__':
    ch = int(sys.argv[1]) if len(sys.argv) > 1 else 50
    asyncio.run(run_mwr_polish(ch))
