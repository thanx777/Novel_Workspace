"""
AI 助理对话 — /api/v2/projects/{project_name}/assistant/...

注意：此文件与 api/chat.py（引擎对话，属于 v2_router）不同。
本模块的 router 在 main.py 中独立挂载。
"""
import os
import re
from typing import List, Optional, Tuple

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from .shared import limiter, safe_join
from .auth import require_auth
from project_db import ProjectDB, get_project_file, get_project_dir
from assistant import ProjectAssistant

router = APIRouter(prefix="/api", tags=["assistant"])


# ── Request models ───────────────────────────────────────────────────

class _AssistantChat(BaseModel):
    message: str = ""
    presets: List[dict] = []


class _AiAddCharacter(BaseModel):
    description: str
    presets: List[dict] = []
    preset_name: str = ""


class _DeleteCharacter(BaseModel):
    name: str
    presets: List[dict] = []
    preset_name: str = ""


# ── Helper ───────────────────────────────────────────────────────────

def _remove_character_from_md(md: str, name: str) -> Tuple[str, bool]:
    """
    从 characters.md 中删除名为 name 的角色块。
    块定义为：以 N. **name** 开头的行（后跟缩进属性），直到下一个 N. 块或 ## 标题前。
    返回 (new_md, found)。
    """
    lines = md.split("\n")
    out = []
    i = 0
    found = False
    name_pat = re.compile(r"^\s*\d+[\.、]\s*\**" + re.escape(name) + r"\**\s*[:：]?\s*$")
    while i < len(lines):
        line = lines[i]
        if not found and name_pat.match(line):
            found = True
            i += 1
            while i < len(lines):
                nxt = lines[i]
                if re.match(r"^\s*\d+[\.、]\s*\*", nxt) or nxt.lstrip().startswith("## "):
                    break
                if nxt.lstrip().startswith("# ") and not nxt.lstrip().startswith("## "):
                    break
                i += 1
            continue
        out.append(line)
        i += 1
    return ("\n".join(out), found)


# ── Endpoints ────────────────────────────────────────────────────────

@router.post("/v2/projects/{project_name}/assistant/chat")
@limiter.limit("10/minute")
def v2_assistant_chat(request: Request, project_name: str, body: _AssistantChat):
    """项目 AI 助理：结合项目上下文，自然语言问答。"""
    try:
        pa = ProjectAssistant(project_name, body.presets or [])
        reply = pa.chat(body.message)
        return {"success": True, "reply": reply, "project_name": project_name}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/v2/projects/{project_name}/delete-character")
@limiter.limit("60/minute")
def v2_delete_character(request: Request, project_name: str, body: _DeleteCharacter):
    """删除指定名称的角色。"""
    try:
        if not body.name.strip():
            raise HTTPException(status_code=400, detail="角色名不能为空")

        char_path = get_project_file(project_name, "characters.md")
        if not os.path.exists(char_path):
            raise HTTPException(status_code=404, detail="characters.md 不存在")

        with open(char_path, "r", encoding="utf-8") as f:
            content = f.read()

        target = body.name.strip()
        new_content, found = _remove_character_from_md(content, target)
        if not found:
            for ch in [target.replace(" ", ""), target.replace("：", ":"), target.strip("**")]:
                new_content, found = _remove_character_from_md(content, ch)
                if found:
                    break

        if not found:
            raise HTTPException(status_code=404, detail=f"未找到角色「{target}」")

        new_content = re.sub(r"\n{3,}", "\n\n", new_content).rstrip() + "\n"

        with open(char_path, "w", encoding="utf-8") as f:
            f.write(new_content)

        db = ProjectDB(project_name)
        db.add_memory("character", f"删除角色：{target}", 0)
        db.close()

        return {
            "success": True,
            "removed": target,
            "file_path": "characters.md",
            "size": len(new_content),
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/v2/projects/{project_name}/ai-add-character")
@limiter.limit("10/minute")
def v2_ai_add_character(request: Request, project_name: str, body: _AiAddCharacter):
    """使用 AI 把作者的自然语言人物描述，转换为符合 characters.md 格式的 markdown 并追加。"""
    try:
        if not body.description.strip():
            raise HTTPException(status_code=400, detail="描述不能为空")

        char_path = get_project_file(project_name, "characters.md")
        existing = ""
        if os.path.exists(char_path):
            with open(char_path, "r", encoding="utf-8") as f:
                existing = f.read()

        pa = ProjectAssistant(project_name, body.presets or [], body.preset_name or "")
        new_block = pa.format_character(body.description, existing)

        if not new_block or new_block.startswith("<!--"):
            return {
                "success": False,
                "error": new_block or "AI 未能生成人物条目（请检查 AI 对话模型配置）",
            }

        if not existing.strip():
            db = ProjectDB(project_name)
            info = db.get_project()
            db.close()
            proj_title = info.get("title") or project_name
            new_content = (
                f"# 《{proj_title}》主要人物设定\n\n"
                f"## 人物列表\n\n"
                f"{new_block}\n"
            )
        else:
            marker = "## 人物列表"
            if marker in existing:
                parts = existing.split(marker, 1)
                head = parts[0]
                rest = parts[1]
                m = re.search(r"^## ", rest, flags=re.MULTILINE)
                if m:
                    body_section = rest[:m.start()]
                    tail_section = rest[m.start():]
                    body_section = body_section.rstrip() + "\n\n" + new_block + "\n\n"
                    new_content = head + marker + body_section + tail_section
                else:
                    new_content = existing.rstrip() + "\n\n" + new_block + "\n"
            else:
                new_content = existing.rstrip() + "\n\n" + new_block + "\n"

        os.makedirs(os.path.dirname(char_path), exist_ok=True)
        with open(char_path, "w", encoding="utf-8") as f:
            f.write(new_content)

        db = ProjectDB(project_name)
        db.add_memory("character", f"AI 添加人物设定（{len(new_block)}字）", 0)
        db.close()

        return {
            "success": True,
            "new_block": new_block,
            "file_path": "characters.md",
            "size": len(new_content),
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/v2/projects/{project_name}/assistant/suggest-next")
@limiter.limit("10/minute")
def v2_assistant_suggest_next(request: Request, project_name: str, body: dict = {}):
    """建议下一章节怎么写。"""
    try:
        presets = body.get("presets", []) if body else []
        pa = ProjectAssistant(project_name, presets)
        reply = pa.suggest_next_chapter()
        return {"success": True, "reply": reply}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/v2/projects/{project_name}/assistant/analyze-consistency")
@limiter.limit("10/minute")
def v2_assistant_analyze(request: Request, project_name: str, body: dict = {}):
    """检查全文一致性问题。"""
    try:
        presets = body.get("presets", []) if body else []
        pa = ProjectAssistant(project_name, presets)
        reply = pa.analyze_consistency()
        return {"success": True, "reply": reply}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/v2/projects/{project_name}/chat")
@limiter.limit("60/minute")
def v2_list_chat_history(request: Request, project_name: str):
    """对话历史记录。"""
    try:
        db = ProjectDB(project_name)
        chat = db.list_chat()
        db.close()
        return {"chat": chat}
    except Exception as e:
        return {"chat": [], "error": str(e)}
