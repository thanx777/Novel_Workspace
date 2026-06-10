"""
分层大纲执行器
- L1 → L2 自动串联
- L3 每章前生成
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

# LLM 调用（从 executor 复用）
try:
    from executor import call_llm, AgentConfig
except ImportError:
    async def call_llm(*args, **kwargs):
        # 占位：实际由后端注入
        return "[LLM_NOT_AVAILABLE]"

    class AgentConfig:
        pass


# ============================================================
# 状态机
# ============================================================

class OutlineState(str, Enum):
    L1_PENDING = "L1_PENDING"
    L1_RUNNING = "L1_RUNNING"
    L1_DONE = "L1_DONE"
    L2_RUNNING = "L2_RUNNING"
    L2_DONE = "L2_DONE"
    L3_IDLE = "L3_IDLE"  # 等待章节


STATE_ORDER = [
    OutlineState.L1_PENDING,
    OutlineState.L1_RUNNING,
    OutlineState.L1_DONE,
    OutlineState.L2_RUNNING,
    OutlineState.L2_DONE,
    OutlineState.L3_IDLE,
]


# ============================================================
# 文件路径
# ============================================================

def _outline_path(project_dir: str, layer: str, ext: str = "md", chapter: Optional[int] = None) -> str:
    if layer in ("L1", "L2"):
        return os.path.join(project_dir, f"outline_{layer}.{ext}")
    elif layer == "L3":
        if chapter is None:
            return os.path.join(project_dir, "outline_L3")
        return os.path.join(project_dir, "outline_L3", f"chapter_{chapter}.{ext}")
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
            "L3_chapters_generated": [],
            "layers_enabled": {"L1": True, "L2": True, "L3": True},
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
        """返回 3 层大纲的元信息。"""
        out = {}
        for layer in ("L1", "L2", "L3"):
            enabled = self.state.get("layers_enabled", {}).get(layer, True)
            if layer in ("L1", "L2"):
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
            else:
                # L3
                l3_dir = _outline_path(self.project_dir, layer)
                chapters = self.state.get("L3_chapters_generated", [])
                out[layer] = {
                    "enabled": enabled,
                    "exists": len(chapters) > 0,
                    "chapters": chapters,
                    "dir": l3_dir,
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
        """生成 L2 网文精简版大纲。"""
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
        self.state["state"] = OutlineState.L2_RUNNING.value
        self._save_state()
        self.yield_func({"status": "info", "layer": "L2", "message": "🚀 开始生成 L2 网文精简版大纲..."})

        prompt = get_prompt("L2", {"L1_summary": l1_summary})
        md_text = await self._call_llm_for_outline(prompt, layer="L2")

        json_data = parse_markdown_to_json("L2", md_text)
        valid, missing = validate_template("L2", json_data)
        if not valid:
            self.yield_func({"status": "warning", "layer": "L2",
                             "message": f"L2 部分字段缺失: {missing}（仍保存）"})

        # 校验跨层一致性
        consistency_warnings = self._check_l2_consistency(l1_json, json_data)
        if consistency_warnings:
            self.yield_func({"status": "warning", "layer": "L2",
                             "message": f"L2 跨层一致性: {consistency_warnings}"})

        md_path = _outline_path(self.project_dir, "L2", "md")
        json_path = _outline_path(self.project_dir, "L2", "json")
        self._write_atomic(md_path, md_text)
        self._write_atomic(json_path, json.dumps(json_data, ensure_ascii=False, indent=2))

        self._add_outline_nodes_to_graph("L2", json_data, summary=md_text[:300])

        self.state["L2_generated_at"] = time.time()
        self.state["state"] = OutlineState.L2_DONE.value
        self._save_state()

        self.yield_func({"status": "done", "layer": "L2",
                         "message": f"✅ L2 网文精简版大纲生成完成（{len(md_text)} 字）",
                         "path": md_path, "valid": valid, "missing": missing})

        return {"success": True, "md_path": md_path, "json_path": json_path, "valid": valid, "missing": missing}

    # ----- L3 -----

    async def generate_L3(self, chapter_num: int, chapter_title: str = "") -> Dict:
        """为第 N 章生成 L3 单章细纲。"""
        if not self.state.get("layers_enabled", {}).get("L3", True):
            self.yield_func({"status": "skip", "message": "L3 已关闭，跳过生成"})
            return {"skipped": True}

        if self.state.get("state") not in (OutlineState.L2_DONE.value, OutlineState.L3_IDLE.value):
            self.yield_func({"status": "error", "message": "L2 未完成，无法生成 L3"})
            return {"success": False, "error": "L2 not ready"}

        # 读取 L1/L2
        l1_path = _outline_path(self.project_dir, "L1", "json")
        l2_path = _outline_path(self.project_dir, "L2", "json")
        l1_summary = ""
        l2_summary = ""
        l1_json = {}
        l2_json = {}
        if os.path.isfile(l1_path):
            with open(l1_path, "r", encoding="utf-8") as f:
                l1_json = json.load(f)
            l1_summary = self._summarize_l1(l1_json)
        if os.path.isfile(l2_path):
            with open(l2_path, "r", encoding="utf-8") as f:
                l2_json = json.load(f)
            l2_summary = json.dumps(l2_json.get("three_acts", {}), ensure_ascii=False)[:500]

        self.yield_func({"status": "info", "layer": "L3", "chapter": chapter_num,
                         "message": f"🚀 开始生成第 {chapter_num} 章单章细纲..."})

        prompt = get_prompt("L3", {
            "L1_summary": l1_summary,
            "L2_summary": l2_summary,
            "chapter_num": chapter_num,
            "chapter_title": chapter_title or f"第{chapter_num}章",
        })
        md_text = await self._call_llm_for_outline(prompt, layer="L3")

        json_data = parse_markdown_to_json("L3", md_text)
        json_data["chapter_num"] = chapter_num
        json_data["chapter_title"] = chapter_title

        valid, missing = validate_template("L3", json_data)

        # 写文件
        md_path = _outline_path(self.project_dir, "L3", "md", chapter=chapter_num)
        json_path = _outline_path(self.project_dir, "L3", "json", chapter=chapter_num)
        self._write_atomic(md_path, md_text)
        self._write_atomic(json_path, json.dumps(json_data, ensure_ascii=False, indent=2))

        # 入图谱
        node_id = f"outline_L3_chapter_{chapter_num}"
        self.kg.add_node(node_id, "outline_node", f"L3 第{chapter_num}章细纲",
                         summary=md_text[:300],
                         attrs={"layer": "L3", "chapter_num": chapter_num,
                                "purpose": json_data.get("本章核心目的", "")[:100]})
        # 关联到 L1 / L2
        l1_node_id = "outline_L1_root"
        if l1_node_id in self.kg.nodes:
            self.kg.add_edge(f"edge_{node_id}_from_L1", "derived_from", node_id, l1_node_id)
        l2_node_id = "outline_L2_root"
        if l2_node_id in self.kg.nodes:
            self.kg.add_edge(f"edge_{node_id}_from_L2", "derived_from", node_id, l2_node_id)
        self.kg.save()

        # 更新状态
        chapters = self.state.get("L3_chapters_generated", [])
        if chapter_num not in chapters:
            chapters.append(chapter_num)
            chapters.sort()
        self.state["L3_chapters_generated"] = chapters
        self.state["state"] = OutlineState.L3_IDLE.value
        self._save_state()

        self.yield_func({"status": "done", "layer": "L3", "chapter": chapter_num,
                         "message": f"✅ 第 {chapter_num} 章细纲生成完成",
                         "path": md_path, "valid": valid, "missing": missing})

        return {"success": True, "md_path": md_path, "json_path": json_path,
                "valid": valid, "missing": missing, "json_data": json_data}

    # ----- 重新生成 -----

    async def regenerate(self, layer: str, chapter: Optional[int] = None) -> Dict:
        if layer == "L1":
            return await self.generate_L1()
        elif layer == "L2":
            return await self.generate_L2()
        elif layer == "L3":
            if chapter is None:
                return {"success": False, "error": "L3 需要指定 chapter"}
            return await self.generate_L3(chapter, f"第{chapter}章")
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
            text = await call_llm(cfg, prompt, user_prompt, max_tokens=8000, request_timeout_seconds=300)
            if not text or text.startswith("[LLM_ERROR"):
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
            return """# L2 占位
## 一、基础信息
- 书名：示例
- 题材：玄幻
- 风格：爽文
- 核心爽点：升级
## 二、简略世界观
示例
## 三、人物速览
- 主角：示例主角
- 女主/重要伙伴：示例
- 主要反派：示例
## 四、剧情总脉络
- 第一阶段（前期）：开篇
- 第二阶段（中期）：发展
- 第三阶段（后期）：结局
## 五、分阶段剧情节点
- 阶段1（第1-30章）：示例 + 爽点：升级 + 收尾：立稳
"""
        else:
            return """# L3 占位
## 一、本章核心目的
示例
## 二、出场人物
示例
## 三、章节流程
1. 开场
## 四、本章情绪/爽点
示例
## 五、伏笔
FS-001
## 六、衔接下一章内容
示例
"""


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
            r3 = await pipe.generate_L3(1, "开篇")
            print("L3:", r3)
            status = pipe.get_status()
            print("Status:", json.dumps(status, ensure_ascii=False, indent=2)[:500])
        asyncio.run(run())
        print("Self-test passed!")


if __name__ == "__main__":
    _self_test()
