"""引擎公共工具函数。"""
import re
import json


def extract_json_from_response(text: str):
    """从 LLM 响应中提取 JSON，支持嵌套大括号和 markdown 代码块。"""
    # 1. 尝试从 ```json ... ``` 代码块中提取（贪婪匹配，支持嵌套JSON）
    code_block = re.search(r'```(?:json)?\s*(\{.+\})\s*```', text, re.DOTALL)
    if code_block:
        try:
            return json.loads(code_block.group(1))
        except Exception:
            pass
    # 2. 查找包含 "score" 的最外层 JSON 对象（支持嵌套）
    start = text.find('{')
    while start != -1:
        depth = 0
        for i in range(start, len(text)):
            if text[i] == '{':
                depth += 1
            elif text[i] == '}':
                depth -= 1
                if depth == 0:
                    candidate = text[start:i + 1]
                    try:
                        data = json.loads(candidate)
                        if isinstance(data, dict) and "score" in data:
                            return data
                    except Exception:
                        pass
                    break
        start = text.find('{', start + 1)
    # 3. 直接尝试解析整个响应
    try:
        return json.loads(text.strip())
    except Exception:
        return None


def extract_chapter_title(content: str) -> str:
    """从内容中提取章节标题，如 '# 第一章 灵根觉醒' → '灵根觉醒'。"""
    for line in content.strip().split("\n"):
        line = line.strip()
        if not line:
            continue
        if line.startswith("---PREV:") or line.startswith("---CAST:") or line.startswith("---"):
            continue
        m = re.match(r"^#+\s*第[一二三四五六七八九十百千\d]+章\s*(.*)", line)
        if m and m.group(1).strip():
            return m.group(1).strip()
        m = re.match(r"^第[一二三四五六七八九十百千\d]+章\s+(.*)", line)
        if m and m.group(1).strip():
            return m.group(1).strip()
        m = re.match(r"^#+\s*(.+)", line)
        if m and m.group(1).strip():
            title = m.group(1).strip()
            title = re.sub(r"^第[一二三四五六七八九十百千\d]+章\s*", "", title)
            return title.strip() or "第N章"
        continue
    return "第N章"
