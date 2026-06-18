import os
import json

from fastapi import APIRouter, HTTPException

from project_db import ProjectDB, get_project_dir, read_file_safe
from knowledge_graph import KnowledgeGraph
from engines.common.kg_adapter import KGAdapter
from engines.common.llm_client import LLMClient, is_llm_error
from engines.common.genre_adapter import GenreAdapter
from engines.common.hallucination_guard import HallucinationGuardAdapter
from engines.common.utils import extract_chapter_title
from .schemas import AiEditRequest
from .engine_registry import _get_project_presets, _get_project_genre, _get_global_presets

router = APIRouter()


@router.post("/projects/{name}/sync-chapters")
def sync_chapters(name: str):
    """手动触发：从已有章节文件中同步章节标题到数据库。
    只同步已有实际内容的章节，不创建空章节条目。
    """
    import re as _re
    project_dir = get_project_dir(name)
    db = ProjectDB(name)
    chapters_found = {}

    # 1. 从已写好的章节文件中提取标题
    chapters_dir = os.path.join(project_dir, "chapters")
    if os.path.isdir(chapters_dir):
        for fname in os.listdir(chapters_dir):
            m = _re.match(r"第(\d+)章\.txt$", fname)
            if not m:
                continue
            idx = int(m.group(1))
            fpath = os.path.join(chapters_dir, fname)
            try:
                with open(fpath, "r", encoding="utf-8") as f:
                    content = f.read()
                if not content.strip():
                    continue  # 跳过空文件
                # 优先从章节内容中提取标题（内容是最新的）
                title = extract_chapter_title(content)
                if not title or title == "第N章":
                    # 兜底：从 chapter_titles.json 获取标题
                    titles_path = os.path.join(project_dir, "chapter_titles.json")
                    if os.path.isfile(titles_path):
                        try:
                            with open(titles_path, "r", encoding="utf-8") as tf:
                                titles_map = json.load(tf)
                            title = titles_map.get(str(idx), f"第{idx}章")
                        except Exception:
                            title = f"第{idx}章"
                else:
                    title = f"第{idx}章 " + title
                chapters_found[idx] = title
            except Exception:
                chapters_found[idx] = f"第{idx}章"

    # 2. 写入数据库（只写入有内容的章节，补充 word_count 和 status）
    for idx, title in chapters_found.items():
        fpath = os.path.join(project_dir, "chapters", f"第{idx}章.txt")
        content = read_file_safe(fpath, "")
        word_count = len(content.replace(" ", "").replace("\n", "")) if content else 0
        status = "drafted" if content.strip() else "not_started"
        db.upsert_chapter(idx, title=title, word_count=word_count, status=status)

    # 3. 更新 total_chapters（优先从 L1 JSON，其次从 chapter_titles.json，最后数 L2 章节）
    total = 0
    # 3a. 优先从 L1 JSON 的 basic.总章节数 提取（支持范围格式如"120-150"取最大值）
    try:
        l1_json_path = os.path.join(project_dir, "outline_L1.json")
        if os.path.isfile(l1_json_path):
            with open(l1_json_path, "r", encoding="utf-8") as f:
                l1_json = json.load(f)
            tc = l1_json.get("basic", {}).get("总章节数", "")
            if tc:
                tc_str = str(tc).strip()
                range_m = _re.match(r"(\d+)\s*[-–—]\s*(\d+)", tc_str)
                if range_m:
                    total = int(range_m.group(2))
                elif tc_str.isdigit():
                    total = int(tc_str)
    except Exception:
        pass
    # 3b. 从 chapter_titles.json 获取
    if total == 0:
        titles_path = os.path.join(project_dir, "chapter_titles.json")
        if os.path.isfile(titles_path):
            try:
                with open(titles_path, "r", encoding="utf-8") as f:
                    titles_map = json.load(f)
                total = len(titles_map)
            except Exception:
                pass
    # 3c. 数 L2 中的章节标题
    if total == 0:
        l2_path = os.path.join(project_dir, "outline_L2.md")
        if os.path.isfile(l2_path):
            with open(l2_path, "r", encoding="utf-8") as f:
                l2_md = f.read()
            for m in _re.finditer(r"###\s*第\s*(\d+)\s*章", l2_md):
                total += 1
    # 3d. 从 L2 阶段范围推断
    if total == 0:
        l2_path = os.path.join(project_dir, "outline_L2.md")
        if os.path.isfile(l2_path):
            with open(l2_path, "r", encoding="utf-8") as f:
                l2_md = f.read()
            max_ch = 0
            for m in _re.finditer(r"第\s*(\d+)\s*[-–—]\s*(\d+)\s*章", l2_md):
                end_ch = int(m.group(2))
                if end_ch > max_ch:
                    max_ch = end_ch
            if max_ch > 0:
                total = max_ch
    if total > 0:
        db.update_project(total_chapters=total)

    db.close()
    return {"synced": len(chapters_found), "total_chapters": total}


@router.post("/projects/{name}/chapters/{chapter_num}/ai-edit")
async def ai_edit_chapter(name: str, chapter_num: int, req: AiEditRequest):
    """AI修改章节：根据用户指令对已有章节进行修改。"""
    import re as _re

    # a. 获取项目目录
    project_dir = get_project_dir(name)

    # b. 读取章节全文
    chapter_path = os.path.join(project_dir, "chapters", f"第{chapter_num}章.txt")
    if not os.path.isfile(chapter_path):
        raise HTTPException(404, f"章节文件不存在：{chapter_path}")
    chapter_content = read_file_safe(chapter_path, "")
    if not chapter_content.strip():
        raise HTTPException(404, f"章节内容为空：第{chapter_num}章")

    # c. 加载KG
    kg = KnowledgeGraph(project_dir)
    kg.load()

    # d. 创建KGAdapter
    kg_adapter = KGAdapter(kg)

    # e. 获取KG上下文
    character_ctx = kg_adapter.format_character_context()
    foreshadowing_ctx = kg_adapter.format_foreshadowing_context()

    # f. 获取体裁规范
    genre = _get_project_genre(name)
    genre_adapter = GenreAdapter(genre_name=genre)
    genre_injection = genre_adapter.get_writer_injection()

    # g. 获取反幻觉上下文
    hallucination_adapter = HallucinationGuardAdapter()
    hallucination_ctx = hallucination_adapter.get_writing_context(chapter_num)

    # h. 读取前后章摘要
    prev_summary = ""
    next_summary = ""
    prev_path = os.path.join(project_dir, "chapters", f"第{chapter_num - 1}章.txt")
    if os.path.isfile(prev_path):
        prev_text = read_file_safe(prev_path, "")
        prev_summary = prev_text[:300] if prev_text else ""
    next_path = os.path.join(project_dir, "chapters", f"第{chapter_num + 1}章.txt")
    if os.path.isfile(next_path):
        next_text = read_file_safe(next_path, "")
        next_summary = next_text[:300] if next_text else ""

    # i. 构建system_prompt
    system_parts = [
        "你是一位资深小说编辑，擅长根据用户要求修改章节内容。你的任务是：严格按照用户的修改要求，对当前章节进行修改，同时保持与前后章节的连贯性和一致性。",
        "修改原则：\n"
        "1. 只修改用户要求的部分，尽量保留原文中不冲突的内容\n"
        "2. 保持人物性格、说话风格一致\n"
        "3. 保持情节逻辑连贯，不引入矛盾\n"
        "4. 保持文风统一，避免AI痕迹\n"
        "5. 返回修改后的完整章节全文，不要省略任何部分",
    ]
    if character_ctx:
        system_parts.append(character_ctx)
    if foreshadowing_ctx:
        system_parts.append(foreshadowing_ctx)
    if genre_injection:
        system_parts.append(genre_injection)
    if hallucination_ctx:
        system_parts.append(hallucination_ctx)
    system_prompt = "\n\n".join(system_parts)

    # j. 构建user_prompt
    user_parts = [f"【当前章节 — 第{chapter_num}章全文】\n{chapter_content}"]
    if prev_summary:
        user_parts.append(f"【前一章（第{chapter_num - 1}章）开头摘要】\n{prev_summary}")
    if next_summary:
        user_parts.append(f"【后一章（第{chapter_num + 1}章）开头摘要】\n{next_summary}")
    user_parts.append(f"【用户修改要求】\n{req.instruction}")
    user_prompt = "\n\n".join(user_parts)

    # k. 调用LLM
    project_presets = _get_project_presets(name)
    global_presets = _get_global_presets()
    llm = LLMClient(project_presets, global_presets)
    result = await llm.call("chat", system_prompt, user_prompt)

    # l. 内容变空检测
    if not result or not result.strip() or is_llm_error(result):
        return {"error": "AI修改失败，返回内容为空"}

    # 中文字数缩水检测
    original_count = len(_re.findall(r'[\u4e00-\u9fff]', chapter_content))
    result_count = len(_re.findall(r'[\u4e00-\u9fff]', result))
    if original_count > 0 and result_count < original_count * 0.5:
        return {"error": "AI修改后字数大幅缩水，请重试"}

    # m. 同步更新数据库标题
    try:
        title = extract_chapter_title(result)
        db = ProjectDB(name)
        db.upsert_chapter(chapter_index=chapter_num, title=title, status="draft")
        db.close()
    except Exception:
        pass

    # n. 返回修改后全文
    return {"content": result}
