"""KG 适配器测试 — 覆盖 KnowledgeGraph / KGAdapter / _write_entities_to_kg / 并发锁 / 边冲突。

文件系统测试用 tempfile.TemporaryDirectory()。
LLM 调用全部 mock。
"""
import sys
import os
import asyncio
import tempfile
import json

sys.path.insert(0, '.')

from knowledge_graph import KnowledgeGraph
from engines.common.kg_adapter import KGAdapter

PASSED, FAILED = [], []


def run(name, fn):
    # Ensure an event loop exists (asyncio.Lock() in KGAdapter.__init__ needs one)
    # asyncio.run() closes the loop after completion, so we need to recreate it
    try:
        asyncio.get_event_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())
    try:
        r = fn()
        PASSED.append((name, r))
        print(f"  ✅ {name}")
    except Exception as e:
        FAILED.append((name, str(e)))
        print(f"  ❌ {name} → {e}")


# ============ 1. KnowledgeGraph — add_node 添加节点 ============
def t01():
    with tempfile.TemporaryDirectory() as tmp:
        kg = KnowledgeGraph(tmp)
        node = kg.add_node("char_林轩", "character", "林轩", summary="主角")
        assert node["id"] == "char_林轩"
        assert node["type"] == "character"
        assert node["label"] == "林轩"
        assert node["summary"] == "主角"
        assert "char_林轩" in kg.nodes
    return "add_node OK"


# ============ 2. KnowledgeGraph — add_edge 添加边 ============
def t02():
    with tempfile.TemporaryDirectory() as tmp:
        kg = KnowledgeGraph(tmp)
        kg.add_node("char_A", "character", "A")
        kg.add_node("char_B", "character", "B")
        edge = kg.add_edge("rel_A_B", "relates_to", "char_A", "char_B", attrs={"relation": "朋友"})
        assert edge["id"] == "rel_A_B"
        assert edge["type"] == "relates_to"
        assert edge["source"] == "char_A"
        assert edge["target"] == "char_B"
        assert edge["attrs"]["relation"] == "朋友"
        assert len(kg.edges) == 1
    return "add_edge OK"


# ============ 3. KnowledgeGraph — 持久化 save/load ============
def t03():
    with tempfile.TemporaryDirectory() as tmp:
        kg = KnowledgeGraph(tmp)
        kg.add_node("char_林轩", "character", "林轩", summary="主角")
        kg.add_node("ch_1", "chapter", "第1章", attrs={"chapter_num": 1})
        kg.add_edge("e1", "appears_in", "char_林轩", "ch_1")
        assert kg.save() is True

        # 重新加载
        kg2 = KnowledgeGraph(tmp)
        assert kg2.load() is True
        assert len(kg2.nodes) == 2
        assert len(kg2.edges) == 1
        assert kg2.nodes["char_林轩"]["label"] == "林轩"
        assert kg2.edges["e1"]["type"] == "appears_in"
    return "持久化 OK"


# ============ 4. KnowledgeGraph — 非法节点类型抛错 ============
def t04():
    with tempfile.TemporaryDirectory() as tmp:
        kg = KnowledgeGraph(tmp)
        try:
            kg.add_node("bad_id", "invalid_type", "label")
            raise AssertionError("应抛出 ValueError")
        except ValueError as e:
            assert "invalid_type" in str(e) or "Unknown" in str(e)
    return "非法节点类型 OK"


# ============ 5. KnowledgeGraph — get_node / list_nodes 查询 ============
def t05():
    with tempfile.TemporaryDirectory() as tmp:
        kg = KnowledgeGraph(tmp)
        kg.add_node("char_A", "character", "A")
        kg.add_node("char_B", "character", "B")
        kg.add_node("ch_1", "chapter", "第1章")

        node = kg.get_node("char_A")
        assert node is not None
        assert node["label"] == "A"

        # 不存在的节点
        assert kg.get_node("nonexistent") is None

        # 按类型查询
        chars = kg.list_nodes("character")
        assert len(chars) == 2
        chapters = kg.list_nodes("chapter")
        assert len(chapters) == 1

        # 全部节点
        all_nodes = kg.list_nodes()
        assert len(all_nodes) == 3
    return "查询 OK"


# ============ 6. KGAdapter — 初始化与延迟加载 ============
def t06():
    with tempfile.TemporaryDirectory() as tmp:
        adapter = KGAdapter(project_dir=tmp)
        # 初始时 _kg 为 None
        assert adapter._kg is None
        # 访问 kg 属性触发延迟加载
        kg = adapter.kg
        assert kg is not None
        assert isinstance(kg, KnowledgeGraph)
        # 再次访问应返回同一实例
        assert adapter.kg is kg
    return "延迟加载 OK"


# ============ 7. KGAdapter — get_characters 查询角色 ============
def t07():
    with tempfile.TemporaryDirectory() as tmp:
        kg = KnowledgeGraph(tmp)
        kg.add_node("char_林轩", "character", "林轩", summary="主角")
        kg.add_node("char_苏清歌", "character", "苏清歌", summary="女主")
        kg.add_node("ch_1", "chapter", "第1章")

        adapter = KGAdapter(kg=kg, project_dir=tmp)
        chars = adapter.get_characters()
        assert len(chars) == 2
        labels = [c["label"] for c in chars]
        assert "林轩" in labels
        assert "苏清歌" in labels
    return "get_characters OK"


# ============ 8. KGAdapter — _write_entities_to_kg 写入角色 ============
def t08():
    with tempfile.TemporaryDirectory() as tmp:
        kg = KnowledgeGraph(tmp)
        adapter = KGAdapter(kg=kg, project_dir=tmp)

        entities = {
            "characters": [
                {"name": "林轩", "identity": "天剑宗弟子", "status": "筑基境", "relations": ["苏清歌"]},
                {"name": "苏清歌", "identity": "女主", "status": "金丹境", "relations": []},
            ]
        }
        stats = adapter._write_entities_to_kg(entities, chapter_num=1)
        assert stats["characters"] == 2
        assert "char_林轩" in kg.nodes
        assert "char_苏清歌" in kg.nodes
        assert kg.nodes["char_林轩"]["label"] == "林轩"
        # 验证 attrs
        attrs = kg.nodes["char_林轩"]["attrs"]
        assert attrs["identity"] == "天剑宗弟子"
        assert attrs["status"] == "筑基境"
        assert attrs["appearances"] == [1]
    return "写入角色 OK"


# ============ 9. KGAdapter — _write_entities_to_kg 写入伏笔 ============
def t09():
    with tempfile.TemporaryDirectory() as tmp:
        kg = KnowledgeGraph(tmp)
        adapter = KGAdapter(kg=kg, project_dir=tmp)

        entities = {
            "foreshadowings": [
                {"id": "FS-001", "description": "神秘玉佩", "status": "buried"},
                {"id": "FS-002", "description": "灭门真相", "status": "resolved"},
            ]
        }
        stats = adapter._write_entities_to_kg(entities, chapter_num=5)
        assert stats["foreshadowings"] == 2
        assert "foreshadowing_FS-001" in kg.nodes
        assert "foreshadowing_FS-002" in kg.nodes
        # 验证状态
        assert kg.nodes["foreshadowing_FS-001"]["attrs"]["status"] == "buried"
        assert kg.nodes["foreshadowing_FS-001"]["attrs"]["buried_chapter"] == 5
        assert kg.nodes["foreshadowing_FS-002"]["attrs"]["status"] == "resolved"
    return "写入伏笔 OK"


# ============ 10. KGAdapter — _write_entities_to_kg 写入场景 ============
def t10():
    with tempfile.TemporaryDirectory() as tmp:
        kg = KnowledgeGraph(tmp)
        adapter = KGAdapter(kg=kg, project_dir=tmp)

        entities = {
            "scenes": [
                {"name": "青云山", "type": "山", "description": "天剑宗所在"},
                {"name": "天剑宗", "type": "宗门", "description": "修仙宗门"},
            ]
        }
        stats = adapter._write_entities_to_kg(entities, chapter_num=1)
        assert stats["scenes"] == 2
        assert "scene_青云山" in kg.nodes
        assert "scene_天剑宗" in kg.nodes
        assert kg.nodes["scene_青云山"]["attrs"]["type"] == "山"
    return "写入场景 OK"


# ============ 11. KGAdapter — _write_entities_to_kg 写入世界观 ============
def t11():
    with tempfile.TemporaryDirectory() as tmp:
        kg = KnowledgeGraph(tmp)
        adapter = KGAdapter(kg=kg, project_dir=tmp)

        entities = {
            "world_facts": [
                {"name": "修炼体系", "description": "淬体→凝气→筑基→金丹"},
            ]
        }
        stats = adapter._write_entities_to_kg(entities, chapter_num=0)
        assert stats["world_facts"] == 1
        assert "world_修炼体系" in kg.nodes
        assert kg.nodes["world_修炼体系"]["type"] == "world_fact"
    return "写入世界观 OK"


# ============ 12. KGAdapter — _write_entities_to_kg 写入剧情线 ============
def t12():
    with tempfile.TemporaryDirectory() as tmp:
        kg = KnowledgeGraph(tmp)
        adapter = KGAdapter(kg=kg, project_dir=tmp)

        entities = {
            "plot_threads": [
                {"name": "灭门真相", "progress": "林轩发现线索", "characters": ["林轩"]},
            ]
        }
        stats = adapter._write_entities_to_kg(entities, chapter_num=3)
        assert stats["plot_threads"] == 1
        assert "thread_灭门真相" in kg.nodes
        assert kg.nodes["thread_灭门真相"]["type"] == "plot_thread"
        assert kg.nodes["thread_灭门真相"]["attrs"]["latest_chapter"] == 3
    return "写入剧情线 OK"


# ============ 13. KGAdapter — _write_entities_to_kg 写入角色关系 ============
def t13():
    with tempfile.TemporaryDirectory() as tmp:
        kg = KnowledgeGraph(tmp)
        adapter = KGAdapter(kg=kg, project_dir=tmp)

        entities = {
            "relationships": [
                {"source": "林轩", "target": "苏清歌", "relation": "恋人"},
                {"source": "林轩", "target": "萧炎", "relation": "师兄弟"},
            ]
        }
        stats = adapter._write_entities_to_kg(entities, chapter_num=1)
        assert stats["relationships"] == 2
        # 角色节点应被自动创建
        assert "char_林轩" in kg.nodes
        assert "char_苏清歌" in kg.nodes
        assert "char_萧炎" in kg.nodes
        # 关系边应被创建
        assert "rel_林轩_苏清歌" in kg.edges
        assert kg.edges["rel_林轩_苏清歌"]["attrs"]["relation"] == "恋人"
    return "写入角色关系 OK"


# ============ 14. KGAdapter — _write_entities_to_kg 写入 Strand 标签 ============
def t14():
    with tempfile.TemporaryDirectory() as tmp:
        kg = KnowledgeGraph(tmp)
        adapter = KGAdapter(kg=kg, project_dir=tmp)

        entities = {
            "strand": "Quest",
        }
        stats = adapter._write_entities_to_kg(entities, chapter_num=5)
        assert stats["strand_tags"] == 1
        assert "strand_ch5" in kg.nodes
        assert kg.nodes["strand_ch5"]["type"] == "strand_tag"
        assert kg.nodes["strand_ch5"]["attrs"]["strand_type"] == "Quest"
    return "写入 Strand 标签 OK"


# ============ 15. KGAdapter — _write_entities_to_kg 写入爽点和钩子 ============
def t15():
    with tempfile.TemporaryDirectory() as tmp:
        kg = KnowledgeGraph(tmp)
        adapter = KGAdapter(kg=kg, project_dir=tmp)

        entities = {
            "coolpoints": [
                {"type": "越级反杀", "description": "林轩以筑基境击败金丹期敌人"},
            ],
            "hooks": [
                {"type": "悬念钩", "description": "断天剑突然发出异光"},
            ],
        }
        stats = adapter._write_entities_to_kg(entities, chapter_num=10)
        assert stats["coolpoints"] == 1
        assert stats["hooks"] == 1
        # 验证节点存在
        coolpoint_nodes = [n for n in kg.nodes.values() if n["type"] == "coolpoint"]
        assert len(coolpoint_nodes) == 1
        assert coolpoint_nodes[0]["attrs"]["coolpoint_type"] == "越级反杀"

        hook_nodes = [n for n in kg.nodes.values() if n["type"] == "hook"]
        assert len(hook_nodes) == 1
        assert hook_nodes[0]["attrs"]["hook_type"] == "悬念钩"
        assert hook_nodes[0]["attrs"]["resolved"] is False
    return "写入爽点和钩子 OK"


# ============ 16. KGAdapter — 边冲突覆盖（与 test_all.py t26 互补） ============
def t16():
    """通过 _write_entities_to_kg 验证相同 edge_id 覆盖逻辑。"""
    with tempfile.TemporaryDirectory() as tmp:
        kg = KnowledgeGraph(tmp)
        adapter = KGAdapter(kg=kg, project_dir=tmp)

        # 第一次写入关系
        entities1 = {
            "relationships": [
                {"source": "林轩", "target": "苏清歌", "relation": "朋友"},
            ]
        }
        adapter._write_entities_to_kg(entities1, chapter_num=1)
        assert kg.edges["rel_林轩_苏清歌"]["attrs"]["relation"] == "朋友"

        # 第二次写入相同关系，不同 relation（模拟第5章关系变化）
        entities2 = {
            "relationships": [
                {"source": "林轩", "target": "苏清歌", "relation": "恋人"},
            ]
        }
        adapter._write_entities_to_kg(entities2, chapter_num=5)
        # 验证：第二次覆盖第一次
        assert kg.edges["rel_林轩_苏清歌"]["attrs"]["relation"] == "恋人"
        assert len(kg.edges) == 1, f"期望 1 条边，实际 {len(kg.edges)}"
    return "边冲突覆盖 OK"


# ============ 17. KGAdapter — 并发锁机制 ============
def t17():
    """验证 asyncio.Lock 存在且可正常使用。"""
    with tempfile.TemporaryDirectory() as tmp:
        kg = KnowledgeGraph(tmp)
        adapter = KGAdapter(kg=kg, project_dir=tmp)
        # 验证 _lock 是 asyncio.Lock
        assert isinstance(adapter._lock, asyncio.Lock)

        # 验证锁可正常获取和释放
        async def _test_lock():
            async with adapter._lock:
                # 在锁内执行写入
                adapter.add_chapter_node(1, "测试章节", "摘要")
            return "ok"

        result = asyncio.run(_test_lock())
        assert result == "ok"
        assert "chapter_1" in kg.nodes
    return "并发锁机制 OK"


# ============ 18. KGAdapter — _parse_ingest_response 解析 JSON ============
def t18():
    with tempfile.TemporaryDirectory() as tmp:
        kg = KnowledgeGraph(tmp)
        adapter = KGAdapter(kg=kg, project_dir=tmp)

        # 直接 JSON
        response = '{"characters": [{"name": "林轩"}]}'
        data = adapter._parse_ingest_response(response)
        assert "characters" in data
        assert len(data["characters"]) == 1

        # markdown 代码块包裹
        response = '```json\n{"characters": [{"name": "林轩"}]}\n```'
        data = adapter._parse_ingest_response(response)
        assert "characters" in data

        # 嵌套 entities 格式
        response = '{"entities": {"character": [{"name": "林轩"}]}}'
        data = adapter._parse_ingest_response(response)
        # _normalize_ingest_data 应将 character 映射为 characters
        assert "characters" in data
        assert len(data["characters"]) == 1

        # 无效 JSON 返回空 dict
        response = '这不是 JSON'
        data = adapter._parse_ingest_response(response)
        assert data == {}
    return "解析摄取响应 OK"


# ============ 19. KGAdapter — _normalize_ingest_data 规范化 ============
def t19():
    with tempfile.TemporaryDirectory() as tmp:
        kg = KnowledgeGraph(tmp)
        adapter = KGAdapter(kg=kg, project_dir=tmp)

        # 嵌套 entities 格式
        data = {
            "entities": {
                "character": [{"name": "A"}],
                "foreshadowing": [{"id": "FS-001"}],
                "scene": [{"name": "S1"}],
                "world_fact": [{"name": "W1"}],
                "plot_thread": [{"name": "T1"}],
                "relationship": [{"source": "A", "target": "B"}],
                "strand": "Quest",
                "coolpoint": [{"type": "C1"}],
                "hook": [{"type": "H1"}],
            }
        }
        result = adapter._normalize_ingest_data(data)
        # 验证单数 key 被映射为复数 key
        assert "characters" in result
        assert "foreshadowings" in result
        assert "scenes" in result
        assert "world_facts" in result
        assert "plot_threads" in result
        assert "relationships" in result
        # 注意：strand/coolpoint/hook 在嵌套格式中是单数 key
        # 但 _normalize_ingest_data 的 key_map 只映射部分，strand 不在 map 中
    return "规范化 OK"


# ============ 20. KGAdapter — format_character_context 格式化角色上下文 ============
def t20():
    with tempfile.TemporaryDirectory() as tmp:
        kg = KnowledgeGraph(tmp)
        kg.add_node("char_林轩", "character", "林轩", summary="天剑宗弟子")
        kg.add_node("char_苏清歌", "character", "苏清歌", summary="女主")

        adapter = KGAdapter(kg=kg, project_dir=tmp)
        ctx = adapter.format_character_context()
        assert "角色列表" in ctx
        assert "林轩" in ctx
        assert "苏清歌" in ctx
        assert "天剑宗弟子" in ctx

        # 空时返回空字符串
        kg2 = KnowledgeGraph(tmp + "_empty")
        adapter2 = KGAdapter(kg=kg2, project_dir=tmp + "_empty")
        assert adapter2.format_character_context() == ""
    return "format_character_context OK"


# ============ 21. KGAdapter — validate_character_names 验证人名 ============
def t21():
    with tempfile.TemporaryDirectory() as tmp:
        kg = KnowledgeGraph(tmp)
        kg.add_node("char_林轩", "character", "林轩")
        kg.add_node("char_苏清歌", "character", "苏清歌")

        adapter = KGAdapter(kg=kg, project_dir=tmp)
        # 已知角色不应被标记为未知
        unknown = adapter.validate_character_names(["林轩", "苏清歌"])
        assert unknown == []

        # 未知角色应被标记
        unknown = adapter.validate_character_names(["林轩", "神秘人", "苏清歌"])
        assert "神秘人" in unknown
        assert "林轩" not in unknown
    return "validate_character_names OK"


# ============ 22. KGAdapter — validate_foreshadowing_ids 验证伏笔 ID ============
def t22():
    with tempfile.TemporaryDirectory() as tmp:
        kg = KnowledgeGraph(tmp)
        kg.add_node("foreshadowing_FS-001", "foreshadowing", "FS-001 神秘玉佩")
        kg.add_node("foreshadowing_FS-002", "foreshadowing", "FS-002 灭门真相")

        adapter = KGAdapter(kg=kg, project_dir=tmp)
        # 已知伏笔
        unknown = adapter.validate_foreshadowing_ids(["FS-001", "FS-002"])
        assert unknown == []

        # 未知伏笔
        unknown = adapter.validate_foreshadowing_ids(["FS-001", "FS-999"])
        assert "FS-999" in unknown
    return "validate_foreshadowing_ids OK"


# ============ 23. KGAdapter — ai_ingest_chapter 规则 fallback（无 LLM） ============
def t23():
    """无 LLM 配置时应使用规则 fallback 摄取。"""
    with tempfile.TemporaryDirectory() as tmp:
        kg = KnowledgeGraph(tmp)
        adapter = KGAdapter(kg=kg, project_dir=tmp)

        chapter_text = """第1章 开篇

林轩说道：今天天气真好。
苏清歌道：是啊。
他们来到了青云山。
"""
        # 不传 llm_client，应使用规则 fallback
        result = asyncio.run(adapter.ai_ingest_chapter(1, chapter_text, llm_client=None))
        assert "success" in result or "mode" in result
        # 应至少提取到一些角色
        chars = adapter.get_characters()
        # 规则摄取应提取 "林轩" 和 "苏清歌"
        char_names = [c.get("label", "") for c in chars]
        assert "林轩" in char_names or "苏清歌" in char_names, f"应提取角色，实际 {char_names}"
        # 章节节点应被添加
        assert "chapter_1" in kg.nodes
    return "规则 fallback 摄取 OK"


# ============ 24. KGAdapter — ai_ingest_chapter mock LLM 摄取 ============
def t24():
    """mock LLM 客户端，验证 AI 摄取流程。"""
    with tempfile.TemporaryDirectory() as tmp:
        kg = KnowledgeGraph(tmp)
        adapter = KGAdapter(kg=kg, project_dir=tmp)

        # mock LLM 客户端
        class _MockLLM:
            def has_valid_config(self, role):
                return True

            async def call(self, role, system, user):
                return json.dumps({
                    "characters": [
                        {"name": "林轩", "identity": "主角", "status": "筑基境", "relations": []}
                    ],
                    "foreshadowings": [
                        {"id": "FS-001", "description": "神秘玉佩", "status": "buried"}
                    ],
                    "strand": "Quest",
                })

        chapter_text = "第1章 开篇\n\n林轩登场。"
        result = asyncio.run(adapter.ai_ingest_chapter(1, chapter_text, llm_client=_MockLLM()))
        assert result.get("success") is True
        assert result.get("characters") == 1
        assert result.get("foreshadowings") == 1
        # 验证 KG 中有对应节点
        assert "char_林轩" in kg.nodes
        assert "foreshadowing_FS-001" in kg.nodes
    return "mock LLM 摄取 OK"


# ============ 25. KGAdapter — get_active_foreshadowings 活跃伏笔 ============
def t25():
    with tempfile.TemporaryDirectory() as tmp:
        kg = KnowledgeGraph(tmp)
        kg.add_node("foreshadowing_FS-001", "foreshadowing", "FS-001",
                    attrs={"status": "buried", "buried_chapter": 1})
        kg.add_node("foreshadowing_FS-002", "foreshadowing", "FS-002",
                    attrs={"status": "resolved", "buried_chapter": 2, "resolved_chapter": 10})
        kg.add_node("foreshadowing_FS-003", "foreshadowing", "FS-003",
                    attrs={"status": "active", "buried_chapter": 5})

        adapter = KGAdapter(kg=kg, project_dir=tmp)
        # 获取第 10 章之前的活跃伏笔
        active = adapter.get_active_foreshadowings(up_to_chapter=10)
        # buried 和 active 状态的应被包含，resolved 不应被包含
        statuses = [f["attrs"]["status"] for f in active]
        assert "buried" in statuses
        assert "active" in statuses
        assert "resolved" not in statuses

        # 限制章节范围：up_to_chapter=3
        active_3 = adapter.get_active_foreshadowings(up_to_chapter=3)
        ids = [f["label"] for f in active_3]
        # FS-001 (buried_chapter=1, status=buried) 应包含
        assert "FS-001" in ids
        # FS-002 (buried_chapter=2, status=resolved) 不应包含（已 resolved）
        assert "FS-002" not in ids
        # FS-003 (buried_chapter=5, status=active) 不应包含（5 > 3）
        assert "FS-003" not in ids
    return "活跃伏笔 OK"


# ============ 26. KGAdapter — get_chapter_context 完整上下文 ============
def t26():
    with tempfile.TemporaryDirectory() as tmp:
        kg = KnowledgeGraph(tmp)
        kg.add_node("char_林轩", "character", "林轩", summary="主角")
        kg.add_node("foreshadowing_FS-001", "foreshadowing", "FS-001",
                    summary="神秘玉佩", attrs={"status": "buried"})
        kg.add_node("world_修炼体系", "world_fact", "修炼体系", summary="淬体→凝气")
        kg.add_node("chapter_1", "chapter", "第1章", summary="开篇",
                    attrs={"chapter_num": 1})

        adapter = KGAdapter(kg=kg, project_dir=tmp)
        ctx = adapter.get_chapter_context(2)
        # 应包含角色、伏笔、世界观、前情提要
        assert "林轩" in ctx
        assert "FS-001" in ctx
        assert "修炼体系" in ctx
        assert "前情提要" in ctx or "第1章" in ctx
    return "get_chapter_context OK"


# ============ 27. KGAdapter — add_chapter_node 添加章节节点 ============
def t27():
    with tempfile.TemporaryDirectory() as tmp:
        kg = KnowledgeGraph(tmp)
        adapter = KGAdapter(kg=kg, project_dir=tmp)

        adapter.add_chapter_node(5, "第五章 测试", "章节摘要")
        assert "chapter_5" in kg.nodes
        node = kg.nodes["chapter_5"]
        assert node["type"] == "chapter"
        assert node["label"] == "第5章 第五章 测试"
        assert node["attrs"]["chapter_num"] == 5
        assert node["attrs"]["title"] == "第五章 测试"
        assert node["summary"] == "章节摘要"

        # 验证已持久化
        kg2 = KnowledgeGraph(tmp)
        kg2.load()
        assert "chapter_5" in kg2.nodes
    return "add_chapter_node OK"


if __name__ == '__main__':
    print("=" * 70)
    print("  KG 适配器测试 (27 用例)")
    print("=" * 70)
    print()
    run("01. KnowledgeGraph add_node", t01)
    run("02. KnowledgeGraph add_edge", t02)
    run("03. KnowledgeGraph 持久化", t03)
    run("04. KnowledgeGraph 非法节点类型", t04)
    run("05. KnowledgeGraph 查询", t05)
    run("06. KGAdapter 延迟加载", t06)
    run("07. KGAdapter get_characters", t07)
    run("08. KGAdapter 写入角色", t08)
    run("09. KGAdapter 写入伏笔", t09)
    run("10. KGAdapter 写入场景", t10)
    run("11. KGAdapter 写入世界观", t11)
    run("12. KGAdapter 写入剧情线", t12)
    run("13. KGAdapter 写入角色关系", t13)
    run("14. KGAdapter 写入 Strand 标签", t14)
    run("15. KGAdapter 写入爽点和钩子", t15)
    run("16. KGAdapter 边冲突覆盖", t16)
    run("17. KGAdapter 并发锁机制", t17)
    run("18. KGAdapter 解析摄取响应", t18)
    run("19. KGAdapter 规范化数据", t19)
    run("20. KGAdapter format_character_context", t20)
    run("21. KGAdapter validate_character_names", t21)
    run("22. KGAdapter validate_foreshadowing_ids", t22)
    run("23. KGAdapter 规则 fallback 摄取", t23)
    run("24. KGAdapter mock LLM 摄取", t24)
    run("25. KGAdapter 活跃伏笔", t25)
    run("26. KGAdapter get_chapter_context", t26)
    run("27. KGAdapter add_chapter_node", t27)
    print()
    print("=" * 70)
    print(f"  结果:  {len(PASSED)} 通过 / {len(FAILED)} 失败")
    print("=" * 70)
    sys.exit(0 if not FAILED else 1)
