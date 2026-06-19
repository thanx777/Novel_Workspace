"""
Skill data-access layer.

Provides load/save/delete/search operations for skill markdown files
stored under <workspace>/skills/.
"""
import json
import os
import re
from typing import List, Optional, Dict

from .shared import WORKSPACE_DIR


def _skills_dir() -> str:
    d = os.path.join(WORKSPACE_DIR, "skills")
    os.makedirs(d, exist_ok=True)
    return d


def _skill_path(name: str) -> str:
    safe = re.sub(r'[<>:"/\\|?*]', "_", name)
    return os.path.join(_skills_dir(), f"{safe}.md")


def _meta_path(name: str) -> str:
    safe = re.sub(r'[<>:"/\\|?*]', "_", name)
    return os.path.join(_skills_dir(), f"{safe}.json")


def load_all_skills() -> List[Dict]:
    """Return a list of skill metadata dicts."""
    skills = []
    d = _skills_dir()
    for f in sorted(os.listdir(d)):
        if not f.endswith(".json"):
            continue
        path = os.path.join(d, f)
        try:
            with open(path, "r", encoding="utf-8") as fh:
                meta = json.load(fh)
            skills.append(meta)
        except Exception:
            pass
    return skills


def load_skill_content(name: str) -> Optional[Dict]:
    """Return skill content + metadata, or None if not found."""
    md_path = _skill_path(name)
    meta_path = _meta_path(name)
    if not os.path.exists(md_path):
        return None
    with open(md_path, "r", encoding="utf-8") as f:
        content = f.read()
    meta = {}
    if os.path.exists(meta_path):
        try:
            with open(meta_path, "r", encoding="utf-8") as f:
                meta = json.load(f)
        except Exception:
            pass
    return {"name": name, "content": content, **meta}


def save_skill(name: str, content: str, description: str = "", category: str = "custom", tags: Optional[List[str]] = None) -> None:
    """Save a skill's content and metadata."""
    md_path = _skill_path(name)
    meta_path = _meta_path(name)
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(content)
    meta = {
        "name": name,
        "description": description,
        "category": category,
        "tags": tags or [],
    }
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)


def delete_skill(name: str) -> bool:
    """Delete a skill. Returns True if found and deleted."""
    deleted = False
    md_path = _skill_path(name)
    meta_path = _meta_path(name)
    if os.path.exists(md_path):
        os.remove(md_path)
        deleted = True
    if os.path.exists(meta_path):
        os.remove(meta_path)
        deleted = True
    return deleted


def search_skills(query: str) -> List[Dict]:
    """Simple text search across skill names, descriptions, and content."""
    results = []
    q = query.lower()
    for skill in load_all_skills():
        name = skill.get("name", "").lower()
        desc = skill.get("description", "").lower()
        if q in name or q in desc:
            results.append(skill)
            continue
        # Also search content
        data = load_skill_content(skill.get("name", ""))
        if data and q in data.get("content", "").lower():
            results.append(skill)
    return results
