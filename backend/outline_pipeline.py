"""
分层大纲执行器
- L1 → L2 自动串联
- L2 合并了旧版 L2（阶段划分）+ L3（单章细纲）
- 状态机控制
- 与 KnowledgeGraph 集成（L1/L2 完成后入图谱）
"""
import os
import json
import re
import time
import asyncio
from typing import Dict, List, Optional, Callable, Any
from enum import Enum

from outline_templates import (
    TEMPLATES, LAYER_NAMES, get_prompt, parse_markdown_to_json, validate_template,
)
from knowledge_graph import KnowledgeGraph
from engines.common.kg_adapter import KGAdapter

# LLM 调用（从 llm_client 导入）
try:
    from engines.common.llm_client import call_llm, AgentConfig, is_llm_error
except ImportError:
    async def call_llm(*args, **kwargs):
        return "[LLM_NOT_AVAILABLE]"

    class AgentConfig:
        pass

    def is_llm_error(text):
        return bool(text) and text.strip().startswith("[LLM_ERROR")


# ============================================================
# 状态机
# ============================================================

class OutlineState(str, Enum):
    L1_PENDING = "L1_PENDING"
    L1_RUNNING = "L1_RUNNING"
    L1_DONE = "L1_DONE"
    L2_RUNNING = "L2_RUNNING"
    L2_DONE = "L2_DONE"


STATE_ORDER = [
    OutlineState.L1_PENDING,
    OutlineState.L1_RUNNING,
    OutlineState.L1_DONE,
    OutlineState.L2_RUNNING,
    OutlineState.L2_DONE,
]


# ============================================================
# 文件路径
# ============================================================

def _outline_path(project_dir: str, layer: str, ext: str = "md") -> str:
    if layer in ("L1", "L2"):
        return os.path.join(project_dir, f"outline_{layer}.{ext}")
    raise ValueError(f"Unknown layer: {layer}")


# ============================================================
# 主类
# ============================================================

class OutlinePipeline:
    """分层大纲执行器。"""

    STATE_FILENAME = "outline_state.json"

    def __init__(self, project_dir: str, project_name: str,
                 presets: Optional[List[dict]] = None,
                 yield_func: Optional[Callable[[Dict], Any]] = None):
        self.project_dir = project_dir
        self.project_name = project_name
        self.presets = presets or []
        self.yield_func = yield_func or (lambda ev: None)

        # 状态文件
        self.state_path = os.path.join(project_dir, self.STATE_FILENAME)
        self.state = self._load_state()

        # 知识图谱
        self.kg = KnowledgeGraph(project_dir)
        self.kg.load()
        self.kg_adapter = KGAdapter(self.kg)

    def _load_state(self) -> Dict:
        if os.path.isfile(self.state_path):
            try:
                with open(self.state_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return {
            "state": OutlineState.L1_PENDING.value,
            "L1_generated_at": None,
            "L2_generated_at": None,
            "layers_enabled": {"L1": True, "L2": True},
        }

    def _save_state(self):
        try:
            with open(self.state_path, "w", encoding="utf-8") as f:
                json.dump(self.state, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def set_layers_enabled(self, layers: Dict[str, bool]):
        self.state["layers_enabled"] = layers
        self._save_state()

    def get_state(self) -> Dict:
        return self.state

    def get_status(self) -> Dict:
        """返回 2 层大纲的元信息。"""
        out = {}
        for layer in ("L1", "L2"):
            enabled = self.state.get("layers_enabled", {}).get(layer, True)
            md_path = _outline_path(self.project_dir, layer, "md")
            json_path = _outline_path(self.project_dir, layer, "json")
            out[layer] = {
                "enabled": enabled,
                "exists": os.path.isfile(md_path) and os.path.isfile(json_path),
                "md_path": md_path,
                "json_path": json_path,
                "generated_at": self.state.get(f"{layer}_generated_at"),
                "name": LAYER_NAMES[layer],
            }
        out["state"] = self.state.get("state")
        return out

    # ----- L1 -----

    async def generate_L1(self, requirements: str = "") -> Dict:
        """生成 L1 完整版大纲。"""
        if not self.state.get("layers_enabled", {}).get("L1", True):
            self.yield_func({"status": "skip", "message": "L1 已关闭，跳过生成"})
            return {"skipped": True}

        self.state["state"] = OutlineState.L1_RUNNING.value
        self._save_state()
        self.yield_func({"status": "info", "layer": "L1", "message": "🚀 开始生成 L1 完整版全书大纲..."})

        prompt = get_prompt("L1", {"requirements": requirements})
        md_text = await self._call_llm_for_outline(prompt, layer="L1")

        # 解析
        json_data = parse_markdown_to_json("L1", md_text)
        valid, missing = validate_template("L1", json_data)
        if not valid:
            self.yield_func({"status": "warning", "layer": "L1",
                             "message": f"L1 部分字段缺失: {missing}（仍保存）"})

        # 写文件
        md_path = _outline_path(self.project_dir, "L1", "md")
        json_path = _outline_path(self.project_dir, "L1", "json")
        self._write_atomic(md_path, md_text)
        self._write_atomic(json_path, json.dumps(json_data, ensure_ascii=False, indent=2))

        # 入图谱
        self._add_outline_nodes_to_graph("L1", json_data, summary=md_text[:300])

        self.state["L1_generated_at"] = time.time()
        self.state["state"] = OutlineState.L1_DONE.value
        self._save_state()

        self.yield_func({"status": "done", "layer": "L1",
                         "message": f"✅ L1 完整版大纲生成完成（{len(md_text)} 字）",
                         "path": md_path, "valid": valid, "missing": missing})

        return {"success": True, "md_path": md_path, "json_path": json_path, "valid": valid, "missing": missing}

    # ----- L2 -----

    async def generate_L2(self, l1_json: Optional[Dict] = None) -> Dict:
        """生成 L2 章节细纲。"""
        if not self.state.get("layers_enabled", {}).get("L2", True):
            self.yield_func({"status": "skip", "message": "L2 已关闭，跳过生成"})
            return {"skipped": True}

        # L1 必须先生成
        if self.state.get("state") in (OutlineState.L1_PENDING.value, OutlineState.L1_RUNNING.value):
            self.yield_func({"status": "error", "message": "L1 未完成，无法生成 L2"})
            return {"success": False, "error": "L1 not ready"}

        if l1_json is None:
            json_path = _outline_path(self.project_dir, "L1", "json")
            if not os.path.isfile(json_path):
                return {"success": False, "error": "L1 file not found"}
            with open(json_path, "r", encoding="utf-8") as f:
                l1_json = json.load(f)

        # 构造 L1 摘要作为 context
        l1_summary = self._summarize_l1(l1_json)
        # 提取 L1 总章节数（支持范围格式如"120-150"取最大值）
        tc = l1_json.get("basic", {}).get("总章节数", "")
        tc_int = 0
        if tc:
            tc_str = str(tc).strip()
            range_m = re.match(r"(\d+)\s*[-–—]\s*(\d+)", tc_str)
            if range_m:
                tc_int = int(range_m.group(2))
            elif tc_str.isdigit():
                tc_int = int(tc_str)
        self.state["state"] = OutlineState.L2_RUNNING.value
        self._save_state()

        # ---- 从 L1 提取分卷信息（JSON 优先，md 兜底） ----
        volumes = l1_json.get("volumes", [])
        valid_volumes = [v for v in volumes if v.get("卷总章节")]

        if not valid_volumes:
            # 尝试从 L1 markdown 中提取分卷
            valid_volumes = self._extract_volumes_from_l1_md()

        if not valid_volumes:
            # 无分卷信息，无法生成章节细纲
            self.yield_func({"status": "error", "layer": "L2", "message": "❌ L1 缺少分卷信息，无法生成章节细纲。请重新生成 L1 大纲，确保包含分卷（每卷必须有卷总章节）。"})
            self.state["L2_generated_at"] = time.time()
            self.state["state"] = OutlineState.L2_DONE.value
            self._save_state()
            return {"success": False, "error": "L1 缺少分卷信息"}

        # ---- 按卷分批生成章节细纲 ----
        all_chapters_md = []
        prev_tail = ""

        for i, vol in enumerate(valid_volumes):
            vol_num = vol.get("卷号", i + 1)
            vol_name = vol.get("卷名", f"第{vol_num}卷")
            vol_theme = vol.get("卷核心主题", "")
            vol_conflict = vol.get("卷内核心冲突", "")
            vol_position = vol.get("卷定位", "")

            # 计算章节范围
            start_ch, end_ch = self._calc_volume_chapter_range(valid_volumes, i)
            if start_ch == 0 or end_ch == 0:
                continue

            self.yield_func({
                "status": "info", "layer": "L2",
                "message": f"📝 L2：生成第{vol_num}卷「{vol_name}」（第{start_ch}-{end_ch}章）[{i+1}/{len(valid_volumes)}]..."
            })

            batch_prompt = get_prompt("L2_batch", {
                "L1_summary": l1_summary,
                "phase_name": f"第{vol_num}卷 {vol_name}",
                "start_ch": start_ch,
                "end_ch": end_ch,
                "phase_goal": f"{vol_theme}；{vol_conflict}" if vol_conflict else vol_theme,
                "prev_tail": prev_tail,
            })
            batch_md = await self._call_llm_for_outline(batch_prompt, layer="L2")

            # 提取章节部分
            chapters_part = self._extract_chapters_from_batch(batch_md)
            if chapters_part:
                all_chapters_md.append(chapters_part)
                prev_tail = self._extract_last_chapter_tail(chapters_part)
            else:
                all_chapters_md.append(batch_md)

            # 校验本卷实际生成的章数 vs 预期章数
            actual_count = self._count_chapters_in_md(chapters_part or batch_md)
            expected_count = end_ch - start_ch + 1
            if actual_count < expected_count:
                missing = expected_count - actual_count
                self.yield_func({
                    "status": "warning", "layer": "L2",
                    "message": f"⚠ 第{vol_num}卷预期{expected_count}章，实际生成{actual_count}章，缺少{missing}章，正在补齐..."
                })
                last_actual_ch = start_ch + actual_count - 1
                supplement_md = await self._supplement_chapters(
                    vol_num, vol_name, last_actual_ch + 1, end_ch,
                    vol_theme, vol_conflict, chapters_part or batch_md
                )
                if supplement_md:
                    all_chapters_md[-1] = (chapters_part or batch_md) + "\n\n" + supplement_md
                    prev_tail = self._extract_last_chapter_tail(supplement_md)

            # 每卷生成后立即摄取到 KG，下一卷能看到本卷新增的实体
            vol_md = chapters_part or batch_md
            if vol_md:
                self._add_outline_nodes_to_graph("L2", parse_markdown_to_json("L2", vol_md), summary=vol_md[:300])

        # ---- 合并所有卷的章节细纲 ----
        if all_chapters_md:
            header = self._build_l2_header(valid_volumes)
            final_md = header + "\n\n---\n\n## 逐章细纲\n\n" + "\n\n".join(all_chapters_md)
            final_json = parse_markdown_to_json("L2", final_md)

            md_path = _outline_path(self.project_dir, "L2", "md")
            json_path = _outline_path(self.project_dir, "L2", "json")
            self._write_atomic(md_path, final_md)
            self._write_atomic(json_path, json.dumps(final_json, ensure_ascii=False, indent=2))

            self.yield_func({"status": "info", "layer": "L2",
                             "message": f"✅ L2 章节细纲分批生成完成，共 {len(valid_volumes)} 卷"})
        else:
            md_path = _outline_path(self.project_dir, "L2", "md")
            final_md = ""

        self._add_outline_nodes_to_graph("L2", final_json if all_chapters_md else {}, summary=final_md[:300] if final_md else "")

        self.state["L2_generated_at"] = time.time()
        self.state["state"] = OutlineState.L2_DONE.value
        self._save_state()

        self.yield_func({"status": "done", "layer": "L2",
                         "message": f"✅ L2 章节细纲生成完成（{len(final_md)} 字）",
                         "path": md_path})

        return {"success": True, "md_path": md_path}

    # ----- 重新生成 -----

    async def regenerate(self, layer: str) -> Dict:
        if layer == "L1":
            return await self.generate_L1()
        elif layer == "L2":
            return await self.generate_L2()
        return {"success": False, "error": f"Unknown layer {layer}"}

    # ----- 一键启动 L1→L2 -----

    async def bootstrap_l1_l2(self, requirements: str = "") -> Dict:
        """项目启动时一键生成 L1→L2。"""
        if not self.state.get("layers_enabled", {}).get("L1", True):
            return {"success": False, "error": "L1 已关闭"}
        r1 = await self.generate_L1(requirements)
        if not r1.get("success"):
            return r1
        if not self.state.get("layers_enabled", {}).get("L2", True):
            return r1
        r2 = await self.generate_L2()
        return r2

    # ----- 内部 -----

    def _get_l1_summary(self) -> str:
        """获取 L1 大纲摘要（供 L2 分批生成使用）。"""
        l1_json_path = _outline_path(self.project_dir, "L1", "json")
        if os.path.isfile(l1_json_path):
            try:
                with open(l1_json_path, "r", encoding="utf-8") as f:
                    l1_json = json.load(f)
                return self._summarize_l1(l1_json)
            except Exception:
                pass
        # 兜底：直接读 L1 markdown 前 3000 字
        l1_md_path = _outline_path(self.project_dir, "L1", "md")
        if os.path.isfile(l1_md_path):
            try:
                with open(l1_md_path, "r", encoding="utf-8") as f:
                    return f.read()[:3000]
            except Exception:
                pass
        return ""

    def _summarize_l1(self, l1_json: Dict) -> str:
        """从 L1 JSON 提取摘要（用于 L2 上下文）。"""
        parts = []
        if l1_json.get("basic"):
            b = l1_json["basic"]
            parts.append(f"# L1 摘要\n作品：{b.get('作品名称','')} | 题材：{b.get('题材类型','')} | 主旨：{b.get('故事核心主旨','')}")
        if l1_json.get("worldview"):
            w = l1_json["worldview"]
            parts.append(f"世界观：{w.get('世界背景','')[:100]} | 规则：{w.get('核心规则','')[:100]}")
        if l1_json.get("characters"):
            c = l1_json["characters"]
            main_chars = c.get("核心主角", [])[:3]
            parts.append(f"主角：{', '.join(main_chars) if main_chars else '（无）'}")
            parts.append(f"配角：{', '.join(c.get('主要配角', [])[:3])}")
            parts.append(f"反派：{', '.join(c.get('反派', [])[:3])}")
        if l1_json.get("plot"):
            p = l1_json["plot"]
            parts.append(f"主线：{p.get('主线剧情','')[:200]}")
            parts.append(f"伏笔：{p.get('伏笔清单','')[:200]}")
        if l1_json.get("volumes"):
            for v in l1_json["volumes"][:3]:
                parts.append(f"卷{v.get('卷号','')} {v.get('卷名','')}: 主题={v.get('卷核心主题','')[:50]}")
        return "\n".join(parts)

    def _check_l2_consistency(self, l1_json: Dict, l2_json: Dict) -> List[str]:
        """校验 L2 是否引用了 L1 的人物/伏笔。"""
        warnings = []
        l1_chars = set()
        for c in l1_json.get("characters", {}).get("核心主角", []):
            m = re.match(r"姓名\s*[:：]\s*(\S+)", c)
            if m:
                l1_chars.add(m.group(1))
        l2_chars_text = json.dumps(l2_json.get("characters", {}), ensure_ascii=False)
        for ch in l1_chars:
            if ch and ch not in l2_chars_text:
                warnings.append(f"L2 未引用 L1 主角 '{ch}'")
        l1_foreshadowings = re.findall(r"FS-\d+", l1_json.get("plot", {}).get("伏笔清单", ""))
        l2_text = json.dumps(l2_json, ensure_ascii=False)
        for fs in set(l1_foreshadowings[:5]):
            if fs not in l2_text:
                warnings.append(f"L2 未引用伏笔 {fs}")
        return warnings

    def _extract_volumes_from_l1_md(self) -> List[Dict]:
        """从 L1 markdown 中提取分卷信息（当 L1 JSON 缺少 volumes 时的兜底）。"""
        l1_md_path = _outline_path(self.project_dir, "L1", "md")
        if not os.path.isfile(l1_md_path):
            return []
        with open(l1_md_path, "r", encoding="utf-8") as f:
            l1_md = f.read()
        volumes = []
        vol_pattern = r"###\s*第\s*(\d+)\s*卷\s*[：:]*\s*(.+?)(?=\n###|\n##|\Z)"
        for m in re.finditer(vol_pattern, l1_md, re.DOTALL):
            vol_num = int(m.group(1))
            vol_content = m.group(2)
            vol_name = vol_content.split("\n", 1)[0].strip().strip("：:").strip()
            ch_match = re.search(r"卷总章节\s*[：:]*\s*(\d+)", vol_content)
            if not ch_match:
                ch_match = re.search(r"总章节\s*[：:]*\s*(\d+)", vol_content)
            if not ch_match:
                ch_match = re.search(r"章节数\s*[：:]*\s*(\d+)", vol_content)
            if not ch_match:
                continue
            ch_count = ch_match.group(1)
            theme_match = re.search(r"卷核心主题\s*[：:]*\s*(.+?)(?:\n|$)", vol_content)
            theme = theme_match.group(1).strip() if theme_match else ""
            conflict_match = re.search(r"卷内核心冲突\s*[：:]*\s*(.+?)(?:\n|$)", vol_content)
            conflict = conflict_match.group(1).strip() if conflict_match else ""
            volumes.append({
                "卷号": vol_num,
                "卷名": vol_name,
                "卷总章节": ch_count,
                "卷核心主题": theme,
                "卷内核心冲突": conflict,
            })
        return volumes

    def _calc_volume_chapter_range(self, volumes: List[Dict], vol_index: int) -> tuple:
        """根据分卷信息计算第 vol_index 卷的起止章节号。"""
        start_ch = 1
        for i in range(vol_index):
            ch_count = self._parse_chapter_count(volumes[i].get("卷总章节", ""))
            if ch_count == 0:
                return (0, 0)
            start_ch += ch_count
        ch_count = self._parse_chapter_count(volumes[vol_index].get("卷总章节", ""))
        if ch_count == 0:
            return (0, 0)
        end_ch = start_ch + ch_count - 1
        return (start_ch, end_ch)

    @staticmethod
    def _parse_chapter_count(ch_str: str) -> int:
        """解析 "30章" 或 "30" 格式的章节数。"""
        if not ch_str:
            return 0
        m = re.search(r"(\d+)", str(ch_str))
        return int(m.group(1)) if m else 0

    def _build_l2_header(self, volumes: List[Dict]) -> str:
        """根据 L1 分卷信息生成 L2 头部（分卷概览）。"""
        lines = ["# 章节细纲\n"]
        lines.append("## 分卷概览\n")
        for vol in volumes:
            vol_num = vol.get("卷号", "?")
            vol_name = vol.get("卷名", "")
            vol_chapters = vol.get("卷总章节", "")
            vol_theme = vol.get("卷核心主题", "")
            lines.append(f"- 第{vol_num}卷「{vol_name}」：{vol_chapters} — {vol_theme}")
        return "\n".join(lines)

    def _extract_chapters_from_batch(self, batch_md: str) -> str:
        """从分批生成结果中提取章节细纲部分。"""
        m = re.search(r"###\s*第\s*\d+\s*章", batch_md)
        if m:
            return batch_md[m.start():]
        return batch_md

    def _count_chapters_in_md(self, md_text: str) -> int:
        """统计 markdown 中实际生成的章节数。"""
        if not md_text:
            return 0
        return len(re.findall(r"###\s*第\s*\d+\s*章", md_text))

    async def _supplement_chapters(self, vol_num: int, vol_name: str,
                                    start_ch: int, end_ch: int,
                                    vol_theme: str, vol_conflict: str,
                                    existing_md: str) -> str:
        """补齐缺失的章节细纲。"""
        l1_summary = self._get_l1_summary()
        batch_prompt = get_prompt("L2_batch", {
            "L1_summary": l1_summary,
            "phase_name": f"第{vol_num}卷 {vol_name}（续）",
            "start_ch": start_ch,
            "end_ch": end_ch,
            "phase_goal": f"{vol_theme}；{vol_conflict}" if vol_conflict else vol_theme,
            "prev_tail": self._extract_last_chapter_tail(existing_md),
        })
        # 注入已有章节作为上下文
        last_chapters = existing_md[-3000:] if len(existing_md) > 3000 else existing_md
        user_extra = (
            f"\n\n以下是本卷已生成的最后部分内容，请自然衔接：\n---\n{last_chapters}\n---\n"
            f"请从第{start_ch}章开始生成，不要重复已有章节。"
        )
        batch_md = await self._call_llm_for_outline(batch_prompt + user_extra, layer="L2")
        return self._extract_chapters_from_batch(batch_md)

    def _extract_last_chapter_tail(self, chapters_md: str) -> str:
        """提取最后一章的衔接信息，传给下一批。"""
        matches = list(re.finditer(
            r"[-*]\s*\*{0,2}衔接下章\*{0,2}\s*[：:]\s*(.+?)(?:\n|$)",
            chapters_md
        ))
        if matches:
            return f"【上一阶段最后一章衔接】{matches[-1].group(1).strip()}"
        return ""

    def _add_outline_nodes_to_graph(self, layer: str, json_data: Dict, summary: str = ""):
        """把 L1/L2 的大纲节点入图谱。"""
        node_id = f"outline_{layer}_root"
        self.kg.add_node(node_id, "outline_node", f"{LAYER_NAMES[layer]}",
                         summary=summary,
                         attrs={"layer": layer, "json_path": _outline_path(self.project_dir, layer, "json")})
        # 关联：L2 derived_from L1
        if layer == "L2":
            l1_id = "outline_L1_root"
            if l1_id in self.kg.nodes:
                self.kg.add_edge("edge_L2_from_L1", "derived_from", node_id, l1_id)
        self.kg.save()

    def _write_atomic(self, path: str, content: str):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(content)
        os.replace(tmp, path)

    async def _call_llm_for_outline(self, prompt: str, layer: str) -> str:
        """调用 LLM 生成大纲。"""
        # 注入 KG 上下文
        kg_ctx = self.kg_adapter.get_outline_layer_context(layer)
        if kg_ctx:
            prompt = kg_ctx + "\n\n" + prompt

        if not self.presets:
            # 无预设：返回模板示例内容（开发模式）
            self.yield_func({"status": "warning", "message": f"未配置 LLM 预设，{layer} 使用占位内容"})
            return self._placeholder_outline(layer)
        # 用第一个 preset 调用
        preset = self.presets[0]
        try:
            # 兼容 preset 可能是 dict（来自 DB/前端）或 AgentConfig
            if isinstance(preset, dict):
                cfg = AgentConfig(
                    api_key=preset.get("api_key", ""),
                    base_url=preset.get("base_url", "https://integrate.api.nvidia.com/v1"),
                    model=preset.get("model", "meta/llama-4-maverick-17b-128e-instruct"),
                    api_format=preset.get("api_format", "openai"),
                    chat_template_kwargs=preset.get("chat_template_kwargs"),
                    thinking_mode=preset.get("thinking_mode"),
                )
            else:
                cfg = preset
            user_prompt = f"请按上面的要求生成 {layer} 大纲。严格按 Markdown 格式输出，不要任何额外说明。"
            text = await call_llm(cfg, prompt, user_prompt, max_tokens=16000, request_timeout_seconds=300)
            if not text or is_llm_error(text):
                self.yield_func({"status": "warning", "message": f"LLM 返回异常: {text[:100]}"})
                return self._placeholder_outline(layer)
            return text
        except Exception as e:
            self.yield_func({"status": "error", "message": f"LLM 调用失败: {e}"})
            return self._placeholder_outline(layer)

    def _placeholder_outline(self, layer: str) -> str:
        """无 LLM 时的占位内容。"""
        if layer == "L1":
            return """# L1 占位大纲

## 一、基础信息栏
1. 作品名称：示例
2. 题材类型：玄幻
3. 作品定位：测试
4. 总字数：100万字
5. 故事核心主旨：示例

## 二、世界观设定
1. 世界背景：示例
2. 核心规则：示例
3. 势力划分：示例
4. 特殊元素：示例

## 三、人物设定表
### 1. 核心主角
- 姓名：示例主角

## 四、整体剧情大纲
1. 主线剧情：示例
2. 支线剧情：示例
3. 伏笔清单：FS-001

## 五、分卷大纲
### 第1卷 开篇
- 卷核心主题：开始
- 卷定位：开篇
- 卷总章节：30
- 卷内核心冲突：示例
- 卷关键剧情节点：示例

## 六、结局规划
1. 主线结局：圆满
"""
        elif layer == "L2":
            return """# L2 章节细纲占位
## 一、阶段划分
- 阶段1（第1-10章）：起步 — 主角登场
- 阶段2（第11-20章）：发展 — 实力提升

## 二、逐章细纲

### 第1章 开篇
- **核心目的**：主角登场
- **出场人物**：示例主角
- **章节流程**：
  1. 开场：山村少年
  2. 发展：遭遇奇遇
  3. 冲突：与恶霸对峙
  4. 转折：获得传承
  5. 收尾：踏上旅途
- **情绪/爽点**：逆袭
- **伏笔**：埋设 FS-001
- **衔接下章**：到达城镇
"""
        else:
            return ""


# ============================================================
# 单元测试
# ============================================================

def _self_test():
    import tempfile
    import asyncio
    with tempfile.TemporaryDirectory() as tmp:
        async def run():
            pipe = OutlinePipeline(tmp, "test", presets=[])
            r1 = await pipe.generate_L1("写一个玄幻小说")
            print("L1:", r1)
            r2 = await pipe.generate_L2()
            print("L2:", r2)
            status = pipe.get_status()
            print("Status:", json.dumps(status, ensure_ascii=False, indent=2)[:500])
        asyncio.run(run())
        print("Self-test passed!")


if __name__ == "__main__":
    _self_test()
