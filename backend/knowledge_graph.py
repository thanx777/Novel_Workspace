"""
知识图谱核心模块
- 7 种节点类型：chapter / character / scene / plot_thread / foreshadowing / world_fact / outline_node
- 6 种边类型：appears_in / happens_in / belongs_to / related_to / foreshadows / derived_from
- SQLite 持久化（向后兼容 JSON）
- 上下文检索
- bootstrap_from_markdown（迁移旧数据）
- export_markdown_view（人读视图）
"""
import os
import json
import re
import sqlite3
import time
from typing import Dict, List, Optional, Any, Tuple


# ============================================================
# Schema 定义
# ============================================================

NODE_TYPES = {
    "chapter", "character", "scene", "plot_thread",
    "foreshadowing", "world_fact", "outline_node",
    # 新增：体裁/节奏相关
    "genre_rule",    # 体裁规则节点（禁忌、爽点类型、疲劳词、节奏规则）
    "strand_tag",    # Strand 标签（Quest/Fire/Constellation）
    "coolpoint",     # 爽点事件（装逼打脸/越级反杀等）
    "hook",          # 钩子事件（危机钩/悬念钩/情绪钩等）
}

EDGE_TYPES = {
    "appears_in", "happens_in", "belongs_to",
    "related_to", "foreshadows", "derived_from",
    # 新增：关系/节奏边
    "relates_to",    # 角色间关系（师徒/恋人/敌对等）
    "tagged_as",     # 章节被标注为某 Strand 类型
    "triggers",      # 钩子触发下一章
    "pays_off",      # 爽点兑现伏笔
    "governed_by",   # 受体裁规则约束
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
    "genre_rule": "#ef4444",    # 红
    "strand_tag": "#14b8a6",    # 蓝绿
    "coolpoint": "#f59e0b",     # 琥珀
    "hook": "#8b5cf6",          # 紫罗兰
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
    """知识图谱主类。支持 SQLite 和 JSON 双后端，自动检测并迁移。"""

    GRAPH_FILENAME = "knowledge_graph.json"
    BACKUP_FILENAME = "knowledge_graph.json.bak"
    DB_FILENAME = "kg.db"

    def __init__(self, project_dir: str):
        self.project_dir = project_dir
        self.memory_dir = os.path.join(project_dir, "memory")
        self.graph_path = os.path.join(self.memory_dir, self.GRAPH_FILENAME)
        self.backup_path = os.path.join(self.memory_dir, self.BACKUP_FILENAME)
        self.db_path = os.path.join(self.memory_dir, self.DB_FILENAME)
        self.nodes: Dict[str, Dict] = {}
        self.edges: Dict[str, Dict] = {}
        self._loaded = False
        self._use_sqlite = False

        # 检测后端：如果 kg.db 存在则用 SQLite，否则用 JSON
        # 新项目也会在 save() 时创建 kg.db
        if os.path.isfile(self.db_path):
            self._use_sqlite = True

    # ----- SQLite 内部方法 -----

    def _init_db(self, conn: sqlite3.Connection):
        """初始化 SQLite 数据库表结构。"""
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS kg_nodes (
                id TEXT PRIMARY KEY,
                type TEXT NOT NULL,
                label TEXT NOT NULL,
                properties TEXT
            );
            CREATE TABLE IF NOT EXISTS kg_edges (
                id TEXT PRIMARY KEY,
                source TEXT NOT NULL,
                target TEXT NOT NULL,
                relation TEXT NOT NULL,
                properties TEXT,
                UNIQUE(source, target, relation)
            );
        """)
        conn.commit()

    def _get_conn(self) -> sqlite3.Connection:
        """获取 SQLite 连接（每次创建新连接，避免文件锁问题）。"""
        os.makedirs(self.memory_dir, exist_ok=True)
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _row_to_node(self, row) -> Dict:
        """将 SQLite 行转为节点字典。"""
        props = json.loads(row["properties"]) if row["properties"] else {}
        return {
            "id": row["id"],
            "type": row["type"],
            "label": row["label"],
            "summary": props.pop("summary", ""),
            "attrs": props.pop("attrs", {}),
            "created_at": props.pop("created_at", time.time()),
            "updated_at": props.pop("updated_at", time.time()),
        }

    def _node_to_props(self, node: Dict) -> str:
        """将节点字典中除 id/type/label 外的字段序列化为 JSON properties。"""
        props = {
            "summary": node.get("summary", ""),
            "attrs": node.get("attrs", {}),
            "created_at": node.get("created_at", time.time()),
            "updated_at": node.get("updated_at", time.time()),
        }
        return json.dumps(props, ensure_ascii=False)

    def _row_to_edge(self, row) -> Dict:
        """将 SQLite 行转为边字典。"""
        props = json.loads(row["properties"]) if row["properties"] else {}
        return {
            "id": row["id"],
            "type": row["relation"],
            "source": row["source"],
            "target": row["target"],
            "attrs": props.pop("attrs", {}),
            "created_at": props.pop("created_at", time.time()),
        }

    def _edge_to_props(self, edge: Dict) -> str:
        """将边字典中除 id/source/target/relation 外的字段序列化为 JSON properties。"""
        props = {
            "attrs": edge.get("attrs", {}),
            "created_at": edge.get("created_at", time.time()),
        }
        return json.dumps(props, ensure_ascii=False)

    # ----- 迁移 -----

    def _migrate_json_to_sqlite(self):
        """将现有 knowledge_graph.json 数据导入 kg.db。"""
        if not os.path.isfile(self.graph_path):
            return
        try:
            with open(self.graph_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            return

        conn = self._get_conn()
        try:
            self._init_db(conn)
            # 写入节点
            for node_id, node in data.get("nodes", {}).items():
                props = self._node_to_props(node)
                conn.execute(
                    "INSERT OR REPLACE INTO kg_nodes (id, type, label, properties) VALUES (?, ?, ?, ?)",
                    (node["id"], node["type"], node["label"], props),
                )
            # 写入边
            for edge_id, edge in data.get("edges", {}).items():
                props = self._edge_to_props(edge)
                conn.execute(
                    "INSERT OR REPLACE INTO kg_edges (id, source, target, relation, properties) VALUES (?, ?, ?, ?, ?)",
                    (edge["id"], edge["source"], edge["target"], edge["type"], props),
                )
            conn.commit()
            self._use_sqlite = True
        except Exception:
            conn.rollback()
        finally:
            conn.close()

    # ----- 持久化 -----

    def save(self) -> bool:
        if self._use_sqlite:
            return self._save_sqlite()
        else:
            # 首次保存时尝试迁移到 SQLite
            self._migrate_json_to_sqlite()
            if self._use_sqlite:
                return self._save_sqlite()
            # 无 JSON 可迁移（新项目），直接使用 SQLite
            self._use_sqlite = True
            return self._save_sqlite()

    def _save_sqlite(self) -> bool:
        """将内存中的 nodes/edges 全量写入 SQLite。"""
        conn = self._get_conn()
        try:
            self._init_db(conn)
            conn.execute("DELETE FROM kg_nodes")
            conn.execute("DELETE FROM kg_edges")
            for node_id, node in self.nodes.items():
                props = self._node_to_props(node)
                conn.execute(
                    "INSERT INTO kg_nodes (id, type, label, properties) VALUES (?, ?, ?, ?)",
                    (node["id"], node["type"], node["label"], props),
                )
            for edge_id, edge in self.edges.items():
                props = self._edge_to_props(edge)
                conn.execute(
                    "INSERT INTO kg_edges (id, source, target, relation, properties) VALUES (?, ?, ?, ?, ?)",
                    (edge["id"], edge["source"], edge["target"], edge["type"], props),
                )
            conn.commit()
            return True
        except Exception:
            conn.rollback()
            return False
        finally:
            conn.close()

    def _save_json(self) -> bool:
        """JSON 后端保存（向后兼容）。"""
        os.makedirs(self.memory_dir, exist_ok=True)
        data = {
            "version": "1.0",
            "nodes": self.nodes,
            "edges": self.edges,
            "last_ingest": time.time(),
        }
        # 先写入临时文件，成功后原子替换，并备份旧文件
        tmp_path = self.graph_path + ".tmp"
        try:
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            # 备份当前正式文件（若存在）
            if os.path.isfile(self.graph_path):
                try:
                    if os.path.isfile(self.backup_path):
                        os.remove(self.backup_path)
                    os.rename(self.graph_path, self.backup_path)
                except Exception:
                    pass
            os.replace(tmp_path, self.graph_path)
            return True
        except Exception:
            # 清理临时文件
            try:
                if os.path.isfile(tmp_path):
                    os.remove(tmp_path)
            except Exception:
                pass
            return False

    def load(self) -> bool:
        if self._use_sqlite:
            return self._load_sqlite()
        else:
            # 如果 JSON 不存在但 SQLite 存在（不应发生，但做防御）
            if not os.path.isfile(self.graph_path) and os.path.isfile(self.db_path):
                self._use_sqlite = True
                return self._load_sqlite()
            # 如果 JSON 存在，先尝试加载 JSON，然后迁移到 SQLite
            result = self._load_json()
            if self._loaded and (self.nodes or self.edges):
                self._migrate_json_to_sqlite()
            elif not os.path.isfile(self.graph_path):
                # 新项目：无 JSON 无 SQLite，直接用 SQLite
                self._use_sqlite = True
                conn = self._get_conn()
                try:
                    self._init_db(conn)
                finally:
                    conn.close()
            return result

    def _load_sqlite(self) -> bool:
        """从 SQLite 加载。"""
        if not os.path.isfile(self.db_path):
            self._loaded = True
            return False
        conn = self._get_conn()
        try:
            self._init_db(conn)
            # 加载节点
            rows = conn.execute("SELECT id, type, label, properties FROM kg_nodes").fetchall()
            self.nodes = {}
            for row in rows:
                node = self._row_to_node(row)
                self.nodes[node["id"]] = node
            # 加载边
            rows = conn.execute("SELECT id, source, target, relation, properties FROM kg_edges").fetchall()
            self.edges = {}
            for row in rows:
                edge = self._row_to_edge(row)
                self.edges[edge["id"]] = edge
            self._loaded = True
            return True
        except Exception:
            self.nodes = {}
            self.edges = {}
            self._loaded = True
            return False
        finally:
            conn.close()

    def _load_json(self) -> bool:
        """JSON 后端加载（向后兼容）。"""
        if not os.path.isfile(self.graph_path):
            # 尝试从备份恢复
            if os.path.isfile(self.backup_path):
                try:
                    with open(self.backup_path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    self.nodes = data.get("nodes", {})
                    self.edges = data.get("edges", {})
                    self._loaded = True
                    # 恢复后立即保存为正式文件
                    self._save_json()
                    return True
                except Exception:
                    pass
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
            # 正式文件损坏，尝试从备份恢复
            if os.path.isfile(self.backup_path):
                try:
                    with open(self.backup_path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    self.nodes = data.get("nodes", {})
                    self.edges = data.get("edges", {})
                    self._loaded = True
                    self._save_json()
                    return True
                except Exception:
                    pass
            # 备份也损坏，初始化空图谱
            self.nodes = {}
            self.edges = {}
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
            if self._use_sqlite and os.path.isfile(self.db_path):
                last_ingest = os.path.getmtime(self.db_path)
            elif os.path.isfile(self.graph_path):
                last_ingest = os.path.getmtime(self.graph_path)
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

    # ----- JSON 导入/导出 -----

    def to_dict(self) -> Dict:
        """导出为字典（用于 API 返回和调试）。"""
        self.ensure_loaded()
        return {
            "version": "1.0",
            "nodes": dict(self.nodes),
            "edges": dict(self.edges),
        }

    def from_dict(self, data: Dict):
        """从字典导入（覆盖当前数据）。"""
        self.nodes = data.get("nodes", {})
        self.edges = data.get("edges", {})
        self._loaded = True

    # ----- 关闭 -----

    def close(self):
        """关闭资源（SQLite 连接已在每次操作后关闭，此方法保留兼容）。"""
        pass


# ============================================================
# 单元测试
# ============================================================

def _self_test():
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        # 测试新项目（直接用 SQLite）
        kg = KnowledgeGraph(tmp)
        kg.add_node("char_林轩", "character", "林轩", "主角", {"age": 18})
        kg.add_node("ch_1", "chapter", "第1章 开篇", "林轩出身", {"chapter_num": 1})
        kg.add_node("fs_1", "foreshadowing", "神秘玉佩", "伏笔", {"paid_off": False})
        kg.add_edge("e1", "appears_in", "char_林轩", "ch_1")
        kg.add_edge("e2", "belongs_to", "fs_1", "ch_1")
        assert kg.save()
        assert kg._use_sqlite, "新项目应使用 SQLite 后端"

        # 重新加载（SQLite 后端）
        kg2 = KnowledgeGraph(tmp)
        kg2.load()
        assert kg2._use_sqlite, "已有 kg.db 应使用 SQLite 后端"
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
        # to_dict / from_dict
        d = kg2.to_dict()
        assert len(d["nodes"]) == 3
        assert len(d["edges"]) == 2

        # 测试 JSON 迁移到 SQLite
        tmp2 = os.path.join(tmp, "migration_test")
        os.makedirs(os.path.join(tmp2, "memory"), exist_ok=True)
        json_path = os.path.join(tmp2, "memory", "knowledge_graph.json")
        json_data = {
            "version": "1.0",
            "nodes": {
                "char_A": {"id": "char_A", "type": "character", "label": "角色A", "summary": "测试", "attrs": {}, "created_at": 1.0, "updated_at": 1.0},
            },
            "edges": {
                "e1": {"id": "e1", "type": "appears_in", "source": "char_A", "target": "ch_1", "attrs": {}, "created_at": 1.0},
            },
        }
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(json_data, f)

        kg3 = KnowledgeGraph(tmp2)
        kg3.load()
        # 加载后应自动迁移到 SQLite
        assert kg3._use_sqlite, "加载 JSON 后应迁移到 SQLite"
        assert len(kg3.nodes) == 1
        assert len(kg3.edges) == 1

        print("Self-test passed!")


if __name__ == "__main__":
    _self_test()
