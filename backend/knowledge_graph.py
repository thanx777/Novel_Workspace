"""
知识图谱核心模块
- 7 种节点类型：chapter / character / scene / plot_thread / foreshadowing / world_fact / outline_node
- 6 种边类型：appears_in / happens_in / belongs_to / related_to / foreshadows / derived_from
- JSON 持久化
- 上下文检索
- bootstrap_from_markdown（迁移旧数据）
- export_markdown_view（人读视图）
"""
import os
import json
import re
import time
from typing import Dict, List, Optional, Any, Tuple


# ============================================================
# Schema 定义
# ============================================================

NODE_TYPES = {
    "chapter", "character", "scene", "plot_thread",
    "foreshadowing", "world_fact", "outline_node",
}

EDGE_TYPES = {
    "appears_in", "happens_in", "belongs_to",
    "related_to", "foreshadows", "derived_from",
}

# 节点类型颜色（前端用）
NODE_COLORS = {
    "chapter": "#22c55e",       # 绿
    "character": "#3b82f6",     # 蓝
    "foreshadowing": "#f97316", # 橙
    "outline_node": "#a855f7",  # 紫
    "scene": "#06b6d4",         # 青
    "world_fact": "#6b7280",    # 灰
    "plot_thread": "#eab308",   # 黄
}

LAYER_COLORS = {
    "L1": "#a855f7",
    "L2": "#ec4899",
    "L3": "#f59e0b",
}


# ============================================================
# Node / Edge 模型
# ============================================================

def _new_node(node_id: str, type_: str, label: str, summary: str = "", attrs: Optional[Dict] = None) -> Dict:
    if type_ not in NODE_TYPES:
        raise ValueError(f"Unknown node type: {type_}")
    return {
        "id": node_id,
        "type": type_,
        "label": label,
        "summary": summary,
        "attrs": attrs or {},
        "created_at": time.time(),
        "updated_at": time.time(),
    }


def _new_edge(edge_id: str, type_: str, source: str, target: str, attrs: Optional[Dict] = None) -> Dict:
    if type_ not in EDGE_TYPES:
        raise ValueError(f"Unknown edge type: {type_}")
    return {
        "id": edge_id,
        "type": type_,
        "source": source,
        "target": target,
        "attrs": attrs or {},
        "created_at": time.time(),
    }


# ============================================================
# KnowledgeGraph 类
# ============================================================

class KnowledgeGraph:
    """知识图谱主类。"""

    GRAPH_FILENAME = "knowledge_graph.json"

    def __init__(self, project_dir: str):
        self.project_dir = project_dir
        self.memory_dir = os.path.join(project_dir, "memory")
        self.graph_path = os.path.join(self.memory_dir, self.GRAPH_FILENAME)
        self.nodes: Dict[str, Dict] = {}
        self.edges: Dict[str, Dict] = {}
        self._loaded = False

    # ----- 持久化 -----

    def save(self) -> bool:
        os.makedirs(self.memory_dir, exist_ok=True)
        data = {
            "version": "1.0",
            "nodes": self.nodes,
            "edges": self.edges,
            "last_ingest": time.time(),
        }
        try:
            with open(self.graph_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            return True
        except Exception:
            return False

    def load(self) -> bool:
        if not os.path.isfile(self.graph_path):
            self._loaded = True
            return False
        try:
            with open(self.graph_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.nodes = data.get("nodes", {})
            self.edges = data.get("edges", {})
            self._loaded = True
            return True
        except Exception:
            self._loaded = True
            return False

    def is_loaded(self) -> bool:
        return self._loaded

    def ensure_loaded(self):
        if not self._loaded:
            self.load()

    # ----- 节点 CRUD -----

    def add_node(self, node_id: str, type_: str, label: str, summary: str = "", attrs: Optional[Dict] = None) -> Dict:
        self.ensure_loaded()
        node = _new_node(node_id, type_, label, summary, attrs)
        self.nodes[node_id] = node
        return node

    def update_node(self, node_id: str, label: Optional[str] = None, summary: Optional[str] = None, attrs: Optional[Dict] = None) -> Optional[Dict]:
        self.ensure_loaded()
        node = self.nodes.get(node_id)
        if not node:
            return None
        if label is not None:
            node["label"] = label
        if summary is not None:
            node["summary"] = summary
        if attrs is not None:
            node["attrs"] = {**node.get("attrs", {}), **attrs}
        node["updated_at"] = time.time()
        return node

    def delete_node(self, node_id: str) -> bool:
        self.ensure_loaded()
        if node_id in self.nodes:
            del self.nodes[node_id]
            # 同时删除相关边
            self.edges = {eid: e for eid, e in self.edges.items() if e["source"] != node_id and e["target"] != node_id}
            return True
        return False

    def get_node(self, node_id: str) -> Optional[Dict]:
        self.ensure_loaded()
        return self.nodes.get(node_id)

    def list_nodes(self, type_: Optional[str] = None) -> List[Dict]:
        self.ensure_loaded()
        if type_:
            return [n for n in self.nodes.values() if n["type"] == type_]
        return list(self.nodes.values())

    # ----- 边 CRUD -----

    def add_edge(self, edge_id: str, type_: str, source: str, target: str, attrs: Optional[Dict] = None) -> Dict:
        self.ensure_loaded()
        edge = _new_edge(edge_id, type_, source, target, attrs)
        self.edges[edge_id] = edge
        return edge

    def delete_edge(self, edge_id: str) -> bool:
        self.ensure_loaded()
        if edge_id in self.edges:
            del self.edges[edge_id]
            return True
        return False

    def get_edges_of(self, node_id: str) -> List[Dict]:
        """返回与某节点相关的所有边。"""
        self.ensure_loaded()
        return [e for e in self.edges.values() if e["source"] == node_id or e["target"] == node_id]

    # ----- 统计 -----

    def stats(self) -> Dict:
        self.ensure_loaded()
        by_type = {}
        for n in self.nodes.values():
            by_type[n["type"]] = by_type.get(n["type"], 0) + 1
        edge_by_type = {}
        for e in self.edges.values():
            edge_by_type[e["type"]] = edge_by_type.get(e["type"], 0) + 1
        last_ingest = 0
        try:
            if os.path.isfile(self.graph_path):
                mtime = os.path.getmtime(self.graph_path)
                last_ingest = mtime
        except Exception:
            pass
        return {
            "node_count": len(self.nodes),
            "edge_count": len(self.edges),
            "by_type": by_type,
            "edge_by_type": edge_by_type,
            "last_ingest": last_ingest,
        }

    # ----- 上下文检索 -----

    def query_context(self, chapter_num: int, l3: Optional[Dict] = None, l1: Optional[Dict] = None, l2: Optional[Dict] = None) -> Dict:
        """
        返回第 N 章写作的上下文。
        - 最近 3 章摘要
        - 当前卷核心主题 + 主要人物
        - 该章出场角色（从 L3 细纲读取）
        - 仍未回收的伏笔列表
        - 与本章相关的历史场景
        - L1 相关人物/世界观节点
        - L2 当前阶段要点
        """
        self.ensure_loaded()
        # 最近 3 章
        recent_chapters = sorted(
            [n for n in self.nodes.values() if n["type"] == "chapter"],
            key=lambda n: n["attrs"].get("chapter_num", 0),
        )
        recent = recent_chapters[-3:] if recent_chapters else []
        # 未回收伏笔
        open_foreshadowings = [
            n for n in self.nodes.values()
            if n["type"] == "foreshadowing" and not n["attrs"].get("paid_off", False)
        ]
        # 与本章相关的场景
        related_scenes = []
        for edge in self.edges.values():
            if edge["type"] == "happens_in" and edge["target"] == f"chapter_{chapter_num}":
                node = self.nodes.get(edge["source"])
                if node:
                    related_scenes.append(node)
        # L1 人物/世界观
        l1_related = [n for n in self.nodes.values() if n["type"] in ("character", "world_fact")]
        # L2 阶段
        l2_phase = None
        for n in self.nodes.values():
            if n["type"] == "outline_node" and n["attrs"].get("layer") == "L2":
                l2_phase = n
                break
        return {
            "chapter_num": chapter_num,
            "recent_chapters": [n["label"] for n in recent],
            "open_foreshadowings": [n["label"] for n in open_foreshadowings],
            "related_scenes": [n["label"] for n in related_scenes],
            "l1_characters": [n["label"] for n in l1_related if n["type"] == "character"][:20],
            "l1_world_facts": [n["label"] for n in l1_related if n["type"] == "world_fact"][:10],
            "l2_current_phase": l2_phase["label"] if l2_phase else "",
            "l3": l3 or {},
            "l1": l1 or {},
            "l2": l2 or {},
        }

    # ----- Bootstrap（旧数据迁移）-----

    def bootstrap_from_markdown(self, memory_md_path: str, characters_md_path: str = "", outline_md_path: str = "") -> int:
        """
        从旧的 markdown 文件迁移到图谱。
        返回新增的节点数。
        """
        self.ensure_loaded()
        added = 0
        # characters.md → character 节点
        if characters_md_path and os.path.isfile(characters_md_path):
            try:
                with open(characters_md_path, "r", encoding="utf-8") as f:
                    text = f.read()
                # 解析 "## 姓名" 或 "# 姓名"
                for m in re.finditer(r"^#+\s*(.+?)\n", text, re.MULTILINE):
                    name = m.group(1).strip()
                    if not name or name.startswith("人物") or name.startswith("角色") or len(name) > 30:
                        continue
                    nid = f"char_{name}"
                    if nid not in self.nodes:
                        self.add_node(nid, "character", name, summary=text[m.end():m.end()+200].strip()[:200])
                        added += 1
            except Exception:
                pass
        # novel_memory.md → chapter 节点（解析 [SUMMARY: ...] 块）
        if memory_md_path and os.path.isfile(memory_md_path):
            try:
                with open(memory_md_path, "r", encoding="utf-8") as f:
                    text = f.read()
                for i, m in enumerate(re.finditer(r"\[SUMMARY:\s*(.+?)\]", text, re.DOTALL), 1):
                    content = m.group(1).strip()[:200]
                    nid = f"chapter_migrated_{i}"
                    if nid not in self.nodes:
                        self.add_node(nid, "chapter", f"迁移章节 {i}", summary=content, attrs={"chapter_num": i, "migrated": True})
                        added += 1
            except Exception:
                pass
        # outline.md（旧） → outline_node
        if outline_md_path and os.path.isfile(outline_md_path):
            try:
                with open(outline_md_path, "r", encoding="utf-8") as f:
                    text = f.read()
                # 把整篇作为 L1
                nid = "outline_L1_migrated"
                if nid not in self.nodes:
                    self.add_node(nid, "outline_node", "L1 迁移大纲", summary=text[:500], attrs={"layer": "L1", "migrated": True})
                    added += 1
            except Exception:
                pass
        if added:
            self.save()
        return added

    # ----- 导出 markdown 视图 -----

    def export_markdown_view(self) -> str:
        """把图谱导出为人读的 markdown 视图。"""
        self.ensure_loaded()
        lines = ["# 知识图谱视图\n"]
        # 按类型分组
        for type_ in NODE_TYPES:
            nodes = [n for n in self.nodes.values() if n["type"] == type_]
            if not nodes:
                continue
            lines.append(f"## {type_} ({len(nodes)} 个)\n")
            for n in nodes[:50]:
                lines.append(f"- **{n['label']}**")
                if n.get("summary"):
                    lines.append(f"  - {n['summary'][:150]}")
            if len(nodes) > 50:
                lines.append(f"  - ... 还有 {len(nodes) - 50} 个")
            lines.append("")
        return "\n".join(lines)

    def export_markdown(self) -> str:
        """兼容 memory_manager 接口。"""
        return self.export_markdown_view()


# ============================================================
# 单元测试
# ============================================================

def _self_test():
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        kg = KnowledgeGraph(tmp)
        kg.add_node("char_林轩", "character", "林轩", "主角", {"age": 18})
        kg.add_node("ch_1", "chapter", "第1章 开篇", "林轩出身", {"chapter_num": 1})
        kg.add_node("fs_1", "foreshadowing", "神秘玉佩", "伏笔", {"paid_off": False})
        kg.add_edge("e1", "appears_in", "char_林轩", "ch_1")
        kg.add_edge("e2", "belongs_to", "fs_1", "ch_1")
        assert kg.save()
        # 重新加载
        kg2 = KnowledgeGraph(tmp)
        kg2.load()
        assert len(kg2.nodes) == 3
        assert len(kg2.edges) == 2
        # 统计
        st = kg2.stats()
        print("Stats:", st)
        # 上下文
        ctx = kg2.query_context(1)
        print("Context keys:", list(ctx.keys()))
        # 导出
        md = kg2.export_markdown_view()
        assert "林轩" in md
        print("Self-test passed!")


if __name__ == "__main__":
    _self_test()
