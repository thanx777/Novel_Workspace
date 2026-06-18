"""
两层大纲模板模块
- L1 完整版全书大纲（宏观：世界观、人物、主线、分卷）
- L2 章节细纲（微观：每章的详细剧情、出场人物、爽点、伏笔）

L2 合并了旧版 L2（阶段划分）+ L3（单章细纲），一次性生成所有章节细纲。
"""
import json
import re
from typing import Dict, List, Tuple, Optional

# ============================================================
# L1 完整版全书大纲模板
# ============================================================

TEMPLATE_L1 = """# 完整版全书大纲（适合传统小说/中长篇/10w字+）

请按以下结构生成 **完整版全书大纲**，信息最全防跑偏。

## 一、基础信息栏
1. 作品名称：
2. 题材类型：（玄幻/都市/悬疑/言情/无限流/现实等）
3. 作品定位 & 核心卖点：（一句话概括故事、吸引读者的亮点、风格调性）
4. 总字数 / 预计卷数 / 总章节数：（分别填写，如：100万字 / 5卷 / 200章）
5. 故事核心主旨：（想表达的思想、内核）

---

## 二、世界观设定
1. 世界背景：时代、地域、社会格局、整体环境
2. 核心规则：（力量体系、世界观法则、禁忌、特殊设定，如修炼体系、异能、世界观 bug 限制）
3. 势力划分：正派/反派/中立势力、组织、家族、阵营关系、地盘分布
4. 特殊元素：道具、物种、民俗、秘闻、历史遗留伏笔

---

## 三、人物设定表（主角 + 配角 + 反派，防止人设崩塌）

### 1. 核心主角
- 姓名：
- 外貌 & 形象：
- 年龄 & 身份：
- 性格：优点、缺点、口头禅、行为习惯
- 身世背景：过往经历、心结、执念
- 核心目标：短期目标 / 终极目标
- 能力/天赋：强项、短板、成长线
- 人物弧光：从开篇到结局的性格、心态变化

### 2. 主要配角（伙伴、亲人、导师、盟友）
姓名 + 身份 + 性格 + 作用 + 结局走向

### 3. 反派/对手（核心反派、阶段性反派）
姓名 + 身份 + 动机 + 实力 + 行事风格 + 最终下场

### 4. 路人/功能性角色（可选）

---

## 四、整体剧情大纲（主线 + 副线）

1. **主线剧情**：全书贯穿核心故事线（完整起承转合）
2. **支线剧情**：感情线、冒险线、复仇线、阵营线等（标注支线与主线交汇节点）
3. **伏笔清单**：前期埋设伏笔（编号 FS-001、FS-002、...）、中期回收伏笔、后期终极伏笔

---

## 五、分卷大纲（按卷拆分，大结构）
> 【必填】分卷是 L2 章节细纲的分批依据，缺少分卷将无法生成章节细纲。必须填写每一卷的卷总章节（具体数字，如30）。

### 第X卷 卷名
- 卷核心主题：
- 卷定位：（开篇/成长/转折/高潮/收尾）
- 卷总章节：（必填，填具体数字，如30）
- 卷内核心冲突：
- 卷关键剧情节点（按顺序罗列）：
  1. 开篇事件：
  2. 主要发展：
  3. 重大转折/危机：
  4. 卷末高潮/收尾：
- 本卷人物变化：
- 本卷新增伏笔 / 回收伏笔：（标注 FS-XXX）

---

## 六、结局规划
1. 主线结局：圆满 / 悲剧 / 开放式
2. 主角最终状态：目标是否达成、归宿
3. 反派结局：
4. 各势力/配角最终走向：
5. 遗留彩蛋/番外预留（可选）
"""


# ============================================================
# L2 章节细纲模板（合并旧 L2+L3）
# ============================================================

TEMPLATE_L2 = """# 章节细纲（基于 L1 全书大纲，逐章展开）

请基于 **L1 完整版大纲** 生成所有章节的详细细纲。要求：
- 引用 L1 中的人物名/伏笔 ID（FS-XXX），保证跨层一致性
- 每章都要有明确的剧情推进、爽点/悬念设计
- 章节之间自然衔接，节奏张弛有度

## 逐章细纲
> 每章必须严格按以下格式输出，不得省略任何字段

### 第1章 章节标题
- **核心目的**：（推进剧情 / 塑造人物 / 制造冲突 / 埋伏笔 / 发福利）
- **出场人物**：（用 L1 中的人物名）
- **章节流程**：
  1. 开场：
  2. 发展：
  3. 冲突/互动：
  4. 转折/小高潮：
  5. 收尾/留悬念：
- **情绪/爽点**：（升级/打脸/逆袭/甜宠/解谜/虐心等）
- **伏笔**：埋设 FS-XXX / 回收 FS-XXX
- **衔接下章**：下一章开场 + 主要冲突

### 第2章 章节标题
- **核心目的**：
- **出场人物**：
- **章节流程**：
  1. 开场：
  2. 发展：
  3. 冲突/互动：
  4. 转折/小高潮：
  5. 收尾/留悬念：
- **情绪/爽点**：
- **伏笔**：埋设 FS-XXX / 回收 FS-XXX
- **衔接下章**：

（依此类推，为每一章都生成细纲）
"""

# L2 分批模板：按卷生成章节细纲（解决长篇截断问题）
TEMPLATE_L2_BATCH = """# 章节细纲 — {phase_name}（第 {start_ch} - {end_ch} 章）

请基于 **L1 全书大纲**，为第 {start_ch} 章到第 {end_ch} 章生成详细细纲。

要求：
- 引用 L1 中的人物名/伏笔 ID（FS-XXX），保证跨层一致性
- 每章都要有明确的剧情推进、爽点/悬念设计
- 章节之间自然衔接，节奏张弛有度
- 本卷核心目标：{phase_goal}

{prev_tail}

## 逐章细纲
> 严格按以下格式输出每一章，不得省略任何字段，不得添加额外说明

### 第{start_ch}章 章节标题
- **核心目的**：（推进剧情 / 塑造人物 / 制造冲突 / 埋伏笔 / 发福利）
- **出场人物**：（用 L1 中的人物名）
- **章节流程**：
  1. 开场：
  2. 发展：
  3. 冲突/互动：
  4. 转折/小高潮：
  5. 收尾/留悬念：
- **情绪/爽点**：（升级/打脸/逆袭/甜宠/解谜/虐心等）
- **伏笔**：埋设 FS-XXX / 回收 FS-XXX
- **衔接下章**：下一章开场 + 主要冲突

### 第{start_ch_next}章 章节标题
- **核心目的**：
- **出场人物**：
- **章节流程**：
  1. 开场：
  2. 发展：
  3. 冲突/互动：
  4. 转折/小高潮：
  5. 收尾/留悬念：
- **情绪/爽点**：
- **伏笔**：埋设 FS-XXX / 回收 FS-XXX
- **衔接下章**：

（依此类推，必须为第 {start_ch} 章到第 {end_ch} 章每一章都生成细纲，共 {chapter_count} 章）
"""


# ============================================================
# 模板字典
# ============================================================

TEMPLATES = {
    "L1": TEMPLATE_L1,
    "L2": TEMPLATE_L2,
    "L2_batch": TEMPLATE_L2_BATCH,
}

LAYER_NAMES = {
    "L1": "完整版全书大纲",
    "L2": "章节细纲",
    "L2_batch": "章节细纲（分批）",
}


# ============================================================
# 校验必填字段
# ============================================================

REQUIRED_FIELDS_L1 = {
    "basic": ["作品名称", "题材类型", "总字数", "故事核心主旨"],
    "worldview": ["世界背景", "核心规则", "势力划分", "特殊元素"],
    "characters": ["核心主角", "主要配角", "反派"],
    "plot": ["主线剧情", "支线剧情", "伏笔清单"],
    "volumes": ["卷核心主题", "卷定位", "卷总章节", "卷内核心冲突", "卷关键剧情节点"],
    "ending": ["主线结局", "主角最终状态", "反派结局"],
}

REQUIRED_FIELDS_L2 = {
    "phases": ["阶段号", "章节范围", "核心目标"],
    "chapters": ["核心目的", "出场人物", "章节流程", "情绪/爽点"],
}


# ============================================================
# 核心 API
# ============================================================

def get_prompt(layer: str, context: Optional[Dict] = None) -> str:
    """
    按 layer 返回 prompt 模板字符串。
    L2 自动 include 上层摘要作为 context。
    L2_batch 按阶段分批生成章节细纲。
    context = {
        "L1_summary": "...",
        "requirements": "...",
        "total_chapters": 120,
        "phase_name": "绝境求生与破局",
        "start_ch": 1,
        "end_ch": 30,
        "phase_goal": "...",
        "prev_tail": "...",  # 上一批最后一章的衔接信息
    }
    """
    if layer not in TEMPLATES:
        raise ValueError(f"Unknown layer: {layer}, must be one of {list(TEMPLATES.keys())}")

    context = context or {}
    template = TEMPLATES[layer]

    if layer == "L1":
        requirements = context.get("requirements", "")
        total_chapters = context.get("total_chapters", 0)
        prefix = f"用户需求：{requirements}\n\n" if requirements else ""
        # 用户指定了总章节数时，强制注入约束引导 LLM 遵守
        if total_chapters and int(total_chapters) > 0:
            prefix += f"""【参考约束 — 请灵活遵守】
用户期望本书约 **{total_chapters} 章**左右。请以此作为参考规划分卷，但可根据故事需要适当增减（±20%以内）。在"基础信息栏"的第4项中填写你最终确定的总章节数，分卷的章节范围之和应等于该最终值。

"""
        return prefix + template

    elif layer == "L2":
        L1_summary = context.get("L1_summary", "")
        total_chapters = context.get("total_chapters", 0)
        prefix = ""
        if L1_summary:
            prefix = f"""# L1 完整版大纲摘要（请基于此生成 L2 章节细纲，引用 L1 中的人物名/伏笔 ID FS-XXX）

{L1_summary}

---

"""
        # 强制注入总章节数约束
        chapter_constraint = ""
        if total_chapters and int(total_chapters) > 0:
            chapter_constraint = f"""

【参考约束 — 请灵活遵守】
用户期望本书约 **{total_chapters} 章**左右。请参考此数量生成章节细纲，但可根据故事需要适当增减。阶段划分中的章节范围之和应等于你最终确定的总章节数。

"""
        return prefix + chapter_constraint + template

    elif layer == "L2_batch":
        L1_summary = context.get("L1_summary", "")
        phase_name = context.get("phase_name", "本阶段")
        start_ch = context.get("start_ch", 1)
        end_ch = context.get("end_ch", 30)
        phase_goal = context.get("phase_goal", "")
        prev_tail = context.get("prev_tail", "")
        prefix = ""
        if L1_summary:
            prefix = f"""# L1 完整版大纲摘要（请基于此生成章节细纲，引用 L1 中的人物名/伏笔 ID FS-XXX）

{L1_summary}

---

"""
        return prefix + template.format(
            phase_name=phase_name,
            start_ch=start_ch,
            start_ch_next=start_ch + 1,
            end_ch=end_ch,
            chapter_count=end_ch - start_ch + 1,
            phase_goal=phase_goal,
            prev_tail=prev_tail,
        )

    return template


def validate_template(layer: str, json_data: Dict, total_chapters: int = 0) -> Tuple[bool, List[str]]:
    """
    校验必填字段，返回 (是否通过, 缺失字段列表)。
    """
    missing = []
    if layer == "L1":
        for section, fields in REQUIRED_FIELDS_L1.items():
            section_data = json_data.get(section, {})
            if not section_data:
                missing.append(f"{section} (整段缺失)")
                continue
            if section == "volumes":
                if not section_data or not isinstance(section_data, list):
                    missing.append("volumes (需要数组)")
                else:
                    for i, vol in enumerate(section_data):
                        for f in fields:
                            if not vol.get(f):
                                missing.append(f"volumes[{i}].{f}")
                        # 校验卷总章节必须是可解析的数字
                        ch_val = vol.get("卷总章节", "")
                        if ch_val:
                            import re
                            if not re.search(r"\d+", str(ch_val)):
                                missing.append(f"volumes[{i}].卷总章节 (需要数字，当前值: '{ch_val}')")
            elif section == "characters":
                for f in fields:
                    if not section_data.get(f):
                        missing.append(f"characters.{f}")
            else:
                for f in fields:
                    if not section_data.get(f):
                        missing.append(f"{section}.{f}")
    elif layer == "L2":
        for section, fields in REQUIRED_FIELDS_L2.items():
            section_data = json_data.get(section)
            if section_data is None:
                missing.append(f"{section} (缺失)")
                continue
            if isinstance(fields, list):
                for f in fields:
                    if isinstance(section_data, dict):
                        if not section_data.get(f):
                            missing.append(f"{section}.{f}")
                    elif isinstance(section_data, list):
                        for i, item in enumerate(section_data):
                            if isinstance(item, dict) and not item.get(f):
                                missing.append(f"{section}[{i}].{f}")
        # L2 章数一致性校验（允许 ±20% 偏差）
        if total_chapters > 0:
            chapters = json_data.get("chapters", [])
            if isinstance(chapters, list):
                actual_count = len(chapters)
                lower = int(total_chapters * 0.8)
                upper = int(total_chapters * 1.2)
                if actual_count < lower or actual_count > upper:
                    missing.append(f"章数偏差较大：参考 {total_chapters} 章，实际生成 {actual_count} 章（允许范围 {lower}-{upper}）")
    return (len(missing) == 0, missing)


# ============================================================
# Markdown → JSON 解析
# ============================================================

def _extract_field(text: str, field: str) -> Optional[str]:
    """从 markdown 中提取 'field：value' 形式的内容。
    停在下一个 'X. ' 列表项、'## ' 标题或文末。
    兼容格式：'*   **field**：value'、'- field: value'、'field：value'
    """
    # 匹配 "* **field**：" 或 "field：" 开头；value 跨多行，到下一项 ##/--- 或 数字列表或文末
    pattern = rf"(?:\*+\s*)?(?:\*\*)?{re.escape(field)}(?:\*\*)?\s*[:：]\s*(.+?)(?=\n\s*(?:\d+\.|\*+\s*\*\*|##\s|---|\Z))"
    m = re.search(pattern, text, re.DOTALL)
    if m:
        return m.group(1).strip()
    return None


def _bullet_field(text: str, field: str) -> str:
    """在 volume 等小节里，匹配 '*   **field**：value' 或 '- **field**：value' 多行值。
    停在下一条非缩进的 '*   **field**：(value)' 行或 '###'/##' 标题。
    容忍 value 里包含的 1./2. 编号子项（如卷关键剧情节点里有 "1. 开篇"）。
    容忍冒号在 ** 内部的情况（如 **卷核心主题：** 而非 **卷核心主题**：）。
    """
    # 字段名要出现在行首（之前可有空格但不能在数字列表项里）
    # 匹配 '* **field**：value' 或 '- **field**：value' 或 '- **field：**value'
    # 容忍冒号在 ** 内部（如 **卷核心主题：**），也容忍冒号后的 ** 闭合标记
    # 停止条件：下一条 - **field** 行（冒号可在 ** 内或外）、### 或 ## 标题
    pattern = rf"(?m)^\s*[\*\-]\s*\*\*{re.escape(field)}\s*[:：]?\s*\*\*\s*[:：]?\s*(.*?)(?=^\s*[\*\-]\s*\*\*[^*]+\*\*\s*[:：]?|^\s*[\*\-]\s*\*\*[^*]+[:：]\s*\*\*\s*[:：]?|^###|^##|\Z)"
    m = re.search(pattern, text, re.DOTALL)
    if m:
        return m.group(1).strip()
    # 退化：'- field: value' 形式（不加粗）
    pattern2 = rf"(?m)^\s*-\s*{re.escape(field)}\s*[:：]\s*(.*?)(?=^\s*-\s|^\s*\*+\s*\*\*|^###|^##|\Z)"
    m2 = re.search(pattern2, text, re.DOTALL)
    if m2:
        return m2.group(1).strip()
    return ""


def _extract_section(text: str, section: str) -> Optional[str]:
    """从 markdown 中提取 '## X' 到下一个 '##' 之间的内容。
    兼容 '## 一、阶段划分' 等带编号前缀的标题。
    注意：不把 '###' 当作 '##' 的边界（避免截断分卷大纲中的各卷内容）。
    """
    # 先尝试精确匹配 "## section"，边界只匹配 ## (非 ###)
    pattern = rf"##\s*{re.escape(section)}\s*(.*?)(?=\n##(?!#)|\Z)"
    m = re.search(pattern, text, re.DOTALL)
    if m:
        return m.group(1).strip()
    # 再尝试带编号前缀 "## X、section" 或 "## X. section"
    pattern2 = rf"##\s*(?:[一二三四五六七八九十\d]+[、.．]\s*)?{re.escape(section)}\s*(.*?)(?=\n##(?!#)|\Z)"
    m2 = re.search(pattern2, text, re.DOTALL)
    if m2:
        return m2.group(1).strip()
    return None


def _parse_volumes(text: str) -> List[Dict]:
    # 解析分卷大纲（"### 第X卷 卷名" 后跟多个 "- field: value" 项）
    volumes = []
    vol_pattern = r"###\s*第\s*(\d+)\s*卷[：:]*\s*(.+?)(?=\n###|\n##|\Z)"
    for m in re.finditer(vol_pattern, text, re.DOTALL):
        vol_num = int(m.group(1))
        vol_content = m.group(2)
        # 第一行可能是 "卷名"（如 "### 第1卷 潜龙在渊"），也可能是 "卷核心主题"
        first_line = vol_content.split("\n", 1)[0].strip().strip("：:").strip()
        # 如果第一行就是 "**field**：value" 形式，说明卷名已经被解析掉了，尝试从 * 卷核心主题** 提取
        if first_line.startswith("**") and "**" in first_line[2:]:
            first_line = ""
        # 重新尝试提取卷名：可能在 * **卷名** 字段
        vol_name = first_line
        if not vol_name:
            mp = re.search(r"\*+\s*\*\*卷名\*\*\s*[:：]\s*(.+)", vol_content)
            if mp:
                vol_name = mp.group(1).strip().split("\n")[0]
        # 字段名兼容（markdown 里可能省略"卷"前缀）
        def _vf(name_variants):
            for n in name_variants:
                v = _bullet_field(vol_content, n)
                if v:
                    return v
            return ""
        volumes.append({
            "卷号": vol_num,
            "卷名": vol_name or f"第{vol_num}卷",
            "卷核心主题": _vf(["卷核心主题", "核心主题"]),
            "卷定位": _vf(["卷定位", "定位"]),
            "卷总章节": re.sub(r"[章篇部]", "", _vf(["卷总章节", "总章节", "卷章节数", "章节数"])).strip(),
            "卷内核心冲突": _vf(["卷内核心冲突", "核心冲突", "卷冲突"]),
            "卷关键剧情节点": _vf(["卷关键剧情节点", "关键剧情节点", "卷剧情节点", "剧情节点"]),
            "本卷人物变化": _vf(["人物变化", "本卷人物变化", "角色变化"]),
            "本卷新增伏笔/回收伏笔": _vf(["伏笔", "本卷新增伏笔/回收伏笔", "本卷新增伏笔", "新增伏笔", "本卷伏笔"]),
        })
    return volumes


def _parse_characters(text: str) -> Dict:
    """解析人物设定表。"""
    characters = {
        "核心主角": [],
        "主要配角": [],
        "反派": [],
        "路人": [],
    }
    # 兼容不同 header 写法（如"反派/对手"、"路人/功能性角色"）
    # 长的别名先匹配（避免"反派"先吃掉"反派/对手"）
    header_aliases = {
        "核心主角": ["核心主角", "主角"],
        "主要配角": ["主要配角", "配角"],
        "反派": ["反派/对手", "反派"],
        "路人": ["路人/功能性角色", "功能性角色", "路人"],
    }
    for idx, header in [(1, "核心主角"), (2, "主要配角"), (3, "反派"), (4, "路人")]:
        section_text = ""
        # 尝试多种 header 写法
        for alias in header_aliases.get(header, [header]):
            t = (
                _extract_section(text, f"{idx}. {alias}")
                or _extract_section(text, f"### {idx}. {alias}")
                or _extract_section(text, alias)
            )
            if t:
                section_text = t
                break
        if not section_text:
            # 兜底：按"### N. xxx" 块匹配
            for alias in header_aliases.get(header, [header]):
                pat = rf"###\s*{idx}\.\s*{re.escape(alias)}\s*(.*?)(?=\n###|\Z)"
                m = re.search(pat, text, re.DOTALL)
                if m:
                    section_text = m.group(1).strip()
                    break
        if not section_text:
            continue
        # 把所有 * **field**：value 合并成多行字符串
        # 主角：通常一段连续行 = 一个人
        if header == "核心主角":
            # 把整个 section 清理为多行字符串
            lines = []
            for line in section_text.split("\n"):
                l = line.strip().lstrip("-").strip()
                if l:
                    lines.append(l)
            characters["核心主角"] = ["\n".join(lines)] if lines else []
        else:
            # 配角/反派/路人：按 姓名+冒号 切分多个人
            # 模式：'*   **苏清歌**:' 或 '*   **苏清歌**：'
            # 合并属于同一个人（直到下一个 '*   **名字**：' 或 '*   **名字**:'）
            people = []
            current_lines = []
            for line in section_text.split("\n"):
                l = line.strip()
                if not l:
                    continue
                l = l.lstrip("-").strip()
                if not l:
                    continue
                # 检测新角色：'*   **名字**：(内容) 或 '*   **名字**：'
                # 关键：行只到 '**名字**:' 后面没有 ':value' 形式
                m_newchar = re.match(r"\*+\s*\*\*([^*]+)\*\*\s*[：:]\s*$", l)
                if m_newchar:
                    # 是新角色起点
                    if current_lines:
                        people.append("\n".join(current_lines))
                    current_lines = [f"**{m_newchar.group(1)}**"]
                    continue
                # 检测角色起点+值（罕见）
                m_newval = re.match(r"\*+\s*\*\*([^*]+)\*\*\s*[：:]\s*(.+)", l)
                if m_newval and not any(k in l for k in ["姓名", "身份", "性格", "作用", "结局", "外貌", "年龄", "身世", "核心目标", "能力", "短板", "成长线", "弧光", "动机", "实力", "行事", "最终下场", "口头禅", "行为", "目的", "阶段"]):
                    # 看起来像新角色名（不是字段名）
                    if current_lines:
                        people.append("\n".join(current_lines))
                    current_lines = [f"**{m_newval.group(1)}**：{m_newval.group(2)}"]
                    continue
                current_lines.append(l)
            if current_lines:
                people.append("\n".join(current_lines))
            characters[header] = people
    return characters


def parse_markdown_to_json(layer: str, md_text: str) -> Dict:
    """
    把 AI 输出的 markdown 解析为结构化 JSON。
    解析失败时回退为 {'raw': md_text, 'parse_error': str}
    """
    try:
        if layer == "L1":
            return _parse_l1_markdown(md_text)
        elif layer == "L2":
            return _parse_l2_markdown(md_text)
        else:
            return {"raw": md_text, "parse_error": f"Unknown layer: {layer}"}
    except Exception as e:
        return {"raw": md_text, "parse_error": str(e)}


def _parse_l1_markdown(md_text: str) -> Dict:
    """解析 L1 完整版大纲。"""
    # 基础信息
    # 先尝试直接从 markdown 中提取 "总字数 / 预计卷数 / 总章节数" 行
    # L1 实际输出格式: "4. **总字数 / 预计卷数 / 总章节数**：约 15-20 万字 / 4 卷 / 120-150 章"
    raw_total = _extract_field(md_text, "总字数") or ""
    if not raw_total:
        # 兜底：直接正则匹配含 "总字数" 的列表行
        m = re.search(r"(?:\d+\.\s*)?\*{0,2}总字数.*?[：:]\s*(.+?)(?=\n\s*(?:\d+\.|\*+\s*\*\*|##\s|---|\Z))", md_text, re.DOTALL)
        if m:
            raw_total = m.group(1).strip()
    # 尝试从 "总字数 / 预计卷数 / 总章节数" 行中提取总章节数
    # 兼容格式：
    #   "约 15-20 万字 / 4 卷 / 120-150 章"
    #   "100万字 / 5卷 / 200章"
    #   "总章节数：120章"
    total_chapters_str = ""
    # 先从 raw_total（总字数字段值）中提取
    tc_match = re.search(r"(\d+)\s*[-–—]\s*(\d+)\s*章", raw_total)
    if tc_match:
        total_chapters_str = tc_match.group(2)  # 范围取最大值
    else:
        tc_match = re.search(r"(\d+)\s*章", raw_total)
        if tc_match:
            total_chapters_str = tc_match.group(1)
    # 如果字段值里没找到，在整个 L1 中搜索
    if not total_chapters_str:
        # 搜索 "总章节数：N" 或 "总章节数：N-M章"
        tc_match = re.search(r"总章节数\s*[：:]*\s*(\d+)\s*[-–—]\s*(\d+)\s*章", md_text)
        if tc_match:
            total_chapters_str = tc_match.group(2)
        else:
            tc_match = re.search(r"总章节数\s*[：:]*\s*(\d+)\s*章?", md_text)
            if tc_match:
                total_chapters_str = tc_match.group(1)
    # 最后兜底：从分卷大纲中累加 "卷总章节"
    if not total_chapters_str:
        volumes_section = _extract_section(md_text, "分卷大纲") or md_text
        vol_total = 0
        for vm in re.finditer(r"卷总章节\*{0,2}\s*[：:]*\s*\*{0,2}\s*(\d+)\s*[-–—]\s*(\d+)", volumes_section):
            vol_total += int(vm.group(2))
        for vm in re.finditer(r"卷总章节\*{0,2}\s*[：:]*\s*\*{0,2}\s*(\d+)", volumes_section):
            vol_total += int(vm.group(1))
        if vol_total > 0:
            total_chapters_str = str(vol_total)
    basic = {
        "作品名称": _extract_field(md_text, "作品名称") or "",
        "题材类型": _extract_field(md_text, "题材类型") or "",
        "作品定位": _extract_field(md_text, "作品定位") or "",
        "总字数": raw_total,
        "总章节数": total_chapters_str,
        "故事核心主旨": _extract_field(md_text, "故事核心主旨") or "",
    }
    # 世界观
    worldview = {
        "世界背景": _extract_field(md_text, "世界背景") or "",
        "核心规则": _extract_field(md_text, "核心规则") or "",
        "势力划分": _extract_field(md_text, "势力划分") or "",
        "特殊元素": _extract_field(md_text, "特殊元素") or "",
    }
    # 人物
    characters = _parse_characters(md_text)
    # 剧情
    plot = {
        "主线剧情": _extract_field(md_text, "主线剧情") or "",
        "支线剧情": _extract_field(md_text, "支线剧情") or "",
        "伏笔清单": _extract_field(md_text, "伏笔清单") or "",
    }
    # 分卷
    volumes_section = _extract_section(md_text, "分卷大纲")
    volumes = _parse_volumes(volumes_section or md_text)
    # 结局
    ending = {
        "主线结局": _extract_field(md_text, "主线结局") or "",
        "主角最终状态": _extract_field(md_text, "主角最终状态") or "",
        "反派结局": _extract_field(md_text, "反派结局") or "",
        "各势力/配角最终走向": _extract_field(md_text, "各势力/配角最终走向") or "",
        "遗留彩蛋": _extract_field(md_text, "遗留彩蛋") or "",
    }
    return {
        "basic": basic,
        "worldview": worldview,
        "characters": characters,
        "plot": plot,
        "volumes": volumes,
        "ending": ending,
    }


def _parse_l2_markdown(md_text: str) -> Dict:
    """解析 L2 章节细纲（合并版）。"""
    # 1. 解析阶段划分
    phases = []
    phases_text = _extract_section(md_text, "阶段划分") or ""
    # 兼容中文括号（）和英文括号()，兼容冒号和破折号
    for m in re.finditer(r"-\s*阶段\s*(\d+)\s*[（(]\s*(.+?)\s*[）)]\s*[：:—\-–]*\s*(.+?)(?:\n|$)", phases_text):
        phases.append({
            "阶段号": int(m.group(1)),
            "章节范围": m.group(2).strip(),
            "核心目标": m.group(3).strip(),
        })

    # 2. 解析逐章细纲
    chapters = []
    # 匹配 "### 第N章 章节标题"
    ch_pattern = r"###\s*第\s*(\d+)\s*章\s*(.*?)(?=\n###\s*第\s*\d+\s*章|\Z)"
    for m in re.finditer(ch_pattern, md_text, re.DOTALL):
        ch_num = int(m.group(1))
        ch_title = m.group(2).strip().split("\n")[0].strip()
        ch_content = m.group(2)

        # 提取各字段
        core_purpose = _bullet_field(ch_content, "核心目的") or ""
        characters = _bullet_field(ch_content, "出场人物") or ""
        flow = _bullet_field(ch_content, "章节流程") or ""
        emotion = _bullet_field(ch_content, "情绪/爽点") or ""
        foreshadow = _bullet_field(ch_content, "伏笔") or ""
        next_ch = _bullet_field(ch_content, "衔接下章") or ""

        chapters.append({
            "chapter_num": ch_num,
            "title": ch_title,
            "核心目的": core_purpose,
            "出场人物": characters,
            "章节流程": flow,
            "情绪/爽点": emotion,
            "伏笔": foreshadow,
            "衔接下章": next_ch,
        })

    return {
        "phases": phases,
        "chapters": chapters,
    }


# ============================================================
# 单元测试
# ============================================================

def _self_test():
    """基础自检。"""
    # L1
    md_l1 = """# 大纲

## 一、基础信息栏
1. 作品名称：测试小说
2. 题材类型：玄幻
3. 作品定位：测试
4. 总字数：100万字
5. 故事核心主旨：测试

## 二、世界观设定
1. 世界背景：测试
2. 核心规则：测试
3. 势力划分：测试
4. 特殊元素：测试

## 三、人物设定表

### 1. 核心主角
- 姓名：林轩
- 外貌：剑眉

### 2. 主要配角
- 姓名：林雪

### 3. 反派
- 姓名：魔王

## 四、整体剧情大纲
1. 主线剧情：测试
2. 支线剧情：测试
3. 伏笔清单：FS-001

## 五、分卷大纲

### 第1卷 起始
- 卷核心主题：开始
- 卷定位：开篇
- 卷总章节：30
- 卷内核心冲突：起步
- 卷关键剧情节点：出场
- 本卷人物变化：成长
- 本卷新增伏笔/回收伏笔：FS-001

## 六、结局规划
1. 主线结局：圆满
2. 主角最终状态：成神
3. 反派结局：被封印
"""
    json_l1 = parse_markdown_to_json("L1", md_l1)
    print("L1 JSON:", json_l1)
    valid, missing = validate_template("L1", json_l1)
    print(f"L1 valid={valid}, missing={missing}")
    assert valid, f"L1 validation failed: {missing}"

    # L2
    md_l2 = """# 章节细纲
## 一、阶段划分
- 阶段1（第1-10章）：起步 — 主角登场
- 阶段2（第11-20章）：发展 — 实力提升

## 二、逐章细纲

### 第1章 初入江湖
- **核心目的**：主角登场
- **出场人物**：林轩
- **章节流程**：
  1. 开场：山村少年
  2. 发展：遭遇奇遇
  3. 冲突：与恶霸对峙
  4. 转折：获得传承
  5. 收尾：踏上旅途
- **情绪/爽点**：逆袭
- **伏笔**：埋设 FS-001
- **衔接下章**：到达城镇

### 第2章 城镇风云
- **核心目的**：拓展世界观
- **出场人物**：林轩、林雪
- **章节流程**：
  1. 开场：初到城镇
  2. 发展：结识伙伴
  3. 冲突：卷入纷争
  4. 转折：发现阴谋
  5. 收尾：决定深入
- **情绪/爽点**：升级
- **伏笔**：回收 FS-001
- **衔接下章**：深入调查
"""
    json_l2 = parse_markdown_to_json("L2", md_l2)
    print("L2 JSON:", json_l2)
    valid, missing = validate_template("L2", json_l2)
    print(f"L2 valid={valid}, missing={missing}")
    print("Self-test passed!")


if __name__ == "__main__":
    _self_test()
