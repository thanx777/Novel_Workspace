"""
多 Agent 流水线
- 5 个 Agent: chapter-scanner / entity-extractor / foreshadowing-tracker / character-builder / graph-reviewer
- 单 Agent 失败不阻塞其他 Agent
- 同章去重
"""
import os
import json
import time
import re
import hashlib
import traceback
from typing import Dict, List, Optional, Any, Callable

from knowledge_graph import KnowledgeGraph

try:
    from executor import call_llm
except ImportError:
    async def call_llm(*args, **kwargs):
        return "[LLM_NOT_AVAILABLE]"


# ============================================================
# 基类
# ============================================================

class BasePipelineAgent:
    """流水线 Agent 基类。"""

    name: str = "base"

    def __init__(self, kg: KnowledgeGraph, log: Optional[Callable[[str], None]] = None):
        self.kg = kg
        self.log = log or (lambda msg: None)

    async def run(self, context: Dict) -> Dict:
        raise NotImplementedError


# ============================================================
# 1. ChapterScanner
# ============================================================

class ChapterScanner(BasePipelineAgent):
    name = "chapter-scanner"

    async def run(self, context: Dict) -> Dict:
        chapter_num = context["chapter_num"]
        chapter_text = context.get("chapter_text", "")
        # 字数
        word_count = len(re.sub(r"\s+", "", chapter_text))
        # 对话数（"..." 计数）
        dialogue_count = len(re.findall(r'["""].+?["""]', chapter_text))
        # 视角：第一章为默认主视角
        pov = "主角"
        # 入图谱
        node_id = f"chapter_{chapter_num}"
        attrs = {
            "chapter_num": chapter_num,
            "word_count": word_count,
            "dialogue_count": dialogue_count,
            "pov": pov,
        }
        self.kg.add_node(node_id, "chapter", f"第{chapter_num}章",
                         summary=chapter_text[:200], attrs=attrs)
        self.kg.save()
        self.log(f"[chapter-scanner] 第{chapter_num}章：{word_count}字，{dialogue_count}段对话")
        return {"word_count": word_count, "dialogue_count": dialogue_count, "pov": pov}


# ============================================================
# 2. EntityExtractor
# ============================================================

class EntityExtractor(BasePipelineAgent):
    name = "entity-extractor"

    async def run(self, context: Dict) -> Dict:
        chapter_num = context["chapter_num"]
        chapter_text = context.get("chapter_text", "")
        characters_md = context.get("characters_md", "")
        # 提取出现的人物：基于 characters.md 匹配
        # characters.md 中角色是 "N. **林轩**" 格式（加粗姓名），从加粗字段中提取
        mentioned = []
        if characters_md:
            char_names = re.findall(r"\*\*([^*\n]+?)\*\*", characters_md)
            char_names = [n.strip() for n in char_names if n.strip() and 1 < len(n.strip()) < 30]
            for name in char_names:
                if name in chapter_text:
                    mentioned.append(name)
        # 提取地名/道具：
        # 1. 把"动词+地名"模式（如"踏入青云山"、"登上寒霜剑阁"）切开，只保留地名
        # 2. 把"介词+地名"模式（如"在青云山"、"从青云山"）切开
        # 简单做法：扫描所有 1-4 汉字+后缀，过滤掉"动词+X"前缀
        loc_suffix = r"山|城|镇|村|谷|派|门|教|宫|殿|阁"
        item_suffix = r"剑|刀|珠|玉|丹|书|卷|令|旗"
        # 动词/介词清单（这些字前面的"X山"是误匹配）
        verb_or_prep = r"踏|登|入|出|上|下|来|去|到|于|在|从|至|经|向|往|穿|绕|经|过|入"
        # 匹配"动词(可叠加)+地名"模式，提取地名
        verb_loc = re.findall(rf"(?:{verb_or_prep})+([一-龥]{{1,4}}{loc_suffix})", chapter_text)
        # 直接出现"在/从/到/于 + 地名"模式
        prep_loc = re.findall(rf"(?<=[在于从到])([一-龥]{{1,4}}{loc_suffix})", chapter_text)
        # 句首/标点后直接出现
        start_loc = re.findall(rf"(?:^|[，。！？、；：「」\"\s])([一-龥]{{1,4}}{loc_suffix})", chapter_text)
        # 合并
        all_locs = verb_loc + prep_loc + start_loc
        locations = list(set(all_locs))
        # 过滤方位词
        locations = [l for l in locations if not any(l.endswith(suf) for suf in ("之巅", "之上", "之下"))]
        # 道具类似
        verb_item = re.findall(rf"(?:{verb_or_prep})+([一-龥]{{1,4}}{item_suffix})", chapter_text)
        prep_item = re.findall(rf"(?<=[在于从到])([一-龥]{{1,4}}{item_suffix})", chapter_text)
        start_item = re.findall(rf"(?:^|[，。！？、；：「」\"\s])([一-龥]{{1,4}}{item_suffix})", chapter_text)
        items = list(set(verb_item + prep_item + start_item))
        # 入图谱
        for ch in mentioned:
            nid = f"char_{ch}"
            if nid not in self.kg.nodes:
                self.kg.add_node(nid, "character", ch, summary=f"第{chapter_num}章首次提及")
            # 出现在本章
            edge_id = f"edge_{nid}_in_chapter_{chapter_num}"
            self.kg.add_edge(edge_id, "appears_in", nid, f"chapter_{chapter_num}",
                             attrs={"chapter_num": chapter_num})
        for loc in locations:
            nid = f"scene_{loc}"
            if nid not in self.kg.nodes:
                self.kg.add_node(nid, "scene", loc, summary=f"第{chapter_num}章出现")
            self.kg.add_edge(f"edge_{nid}_in_ch{chapter_num}", "happens_in", nid, f"chapter_{chapter_num}",
                             attrs={"chapter_num": chapter_num})
        self.kg.save()
        self.log(f"[entity-extractor] 第{chapter_num}章：人物{len(mentioned)} 个，地点{len(locations)} 个，道具{len(items)} 个")
        return {"characters": mentioned, "locations": locations, "items": items}


# ============================================================
# 3. ForeshadowingTracker
# ============================================================

class ForeshadowingTracker(BasePipelineAgent):
    name = "foreshadowing-tracker"

    async def run(self, context: Dict) -> Dict:
        chapter_num = context["chapter_num"]
        chapter_text = context.get("chapter_text", "")
        l3 = context.get("l3", {}) or {}
        # 从 L3 细纲"埋设"和"回收"两段分别提取 FS-XXX
        l3_setup = l3.get("埋设", "") or l3.get("伏笔", "") or ""
        l3_payoff = l3.get("回收", "") or ""
        set_ids = list(set(re.findall(r"FS-\d+", l3_setup)))
        pay_off_ids = list(set(re.findall(r"FS-\d+", l3_payoff)))
        # 标记本章埋设的伏笔
        for fs in set_ids:
            nid = f"foreshadowing_{fs}"
            if nid not in self.kg.nodes:
                self.kg.add_node(nid, "foreshadowing", fs,
                                 summary=f"伏笔 {fs}（首次出现在第{chapter_num}章）",
                                 attrs={"paid_off": False, "set_chapter": chapter_num})
            self.kg.add_edge(f"edge_{nid}_set_in_ch{chapter_num}", "belongs_to", nid, f"chapter_{chapter_num}",
                             attrs={"action": "set", "chapter_num": chapter_num})
        # 标记本章回收的伏笔
        for fs in pay_off_ids:
            nid = f"foreshadowing_{fs}"
            if nid in self.kg.nodes:
                self.kg.update_node(nid, attrs={"paid_off": True, "paid_off_chapter": chapter_num})
            self.kg.add_edge(f"edge_{nid}_paid_in_ch{chapter_num}", "belongs_to", nid, f"chapter_{chapter_num}",
                             attrs={"action": "pay_off", "chapter_num": chapter_num})
        self.kg.save()
        self.log(f"[foreshadowing-tracker] 第{chapter_num}章：埋设 {len(set_ids)} 个，回收 {len(pay_off_ids)} 个")
        return {"set": set_ids, "pay_off": pay_off_ids}


# ============================================================
# 4. CharacterBuilder
# ============================================================

class CharacterBuilder(BasePipelineAgent):
    name = "character-builder"

    async def run(self, context: Dict) -> Dict:
        chapter_num = context["chapter_num"]
        mentioned = context.get("entities", {}).get("characters", [])
        # 更新每个角色的 appearances 计数
        for ch_name in mentioned:
            nid = f"char_{ch_name}"
            node = self.kg.get_node(nid)
            if not node:
                continue
            appearances = node["attrs"].get("appearances", [])
            if chapter_num not in appearances:
                appearances.append(chapter_num)
            self.kg.update_node(nid, attrs={"appearances": appearances,
                                              "latest_chapter": chapter_num,
                                              "latest_state": f"第{chapter_num}章出场"})
        self.kg.save()
        self.log(f"[character-builder] 第{chapter_num}章：更新 {len(mentioned)} 个角色状态")
        return {"updated_characters": mentioned}


# ============================================================
# 5. GraphReviewer
# ============================================================

class GraphReviewer(BasePipelineAgent):
    name = "graph-reviewer"

    async def run(self, context: Dict) -> Dict:
        chapter_num = context["chapter_num"]
        # 检查孤立节点
        orphans = []
        for node in self.kg.list_nodes():
            edges = self.kg.get_edges_of(node["id"])
            if not edges:
                orphans.append(node["id"])
        # 报告
        stats = self.kg.stats()
        self.log(f"[graph-reviewer] 第{chapter_num}章：孤立节点 {len(orphans)} 个，总节点 {stats['node_count']}，边 {stats['edge_count']}")
        return {"orphans": orphans, "stats": stats}


# ============================================================
# IngestPipeline
# ============================================================

class IngestPipeline:
    """多 Agent 增量摄取流水线。"""

    ERROR_LOG = "ingest_errors.log"

    def __init__(self, kg: KnowledgeGraph, project_dir: str,
                 log: Optional[Callable[[str], None]] = None):
        self.kg = kg
        self.project_dir = project_dir
        self.log = log or (lambda msg: None)
        self.agents = [
            ChapterScanner(kg, log),
            EntityExtractor(kg, log),
            ForeshadowingTracker(kg, log),
            CharacterBuilder(kg, log),
            GraphReviewer(kg, log),
        ]

    def _chapter_hash(self, chapter_num: int, chapter_text: str) -> str:
        h = hashlib.sha256()
        h.update(f"{chapter_num}".encode("utf-8"))
        h.update(chapter_text[:5000].encode("utf-8"))
        return h.hexdigest()[:16]

    def _is_processed(self, chapter_num: int, content_hash: str) -> bool:
        """检查章节是否已处理。"""
        marker_path = os.path.join(self.project_dir, "memory", f"ch_{chapter_num}.hash")
        if not os.path.isfile(marker_path):
            return False
        try:
            with open(marker_path, "r") as f:
                return f.read().strip() == content_hash
        except Exception:
            return False

    def _mark_processed(self, chapter_num: int, content_hash: str):
        marker_path = os.path.join(self.project_dir, "memory", f"ch_{chapter_num}.hash")
        os.makedirs(os.path.dirname(marker_path), exist_ok=True)
        with open(marker_path, "w") as f:
            f.write(content_hash)

    async def ingest_chapter(self, chapter_num: int, chapter_text: str,
                              l3: Optional[Dict] = None,
                              characters_md: Optional[str] = None,
                              l1: Optional[Dict] = None,
                              l2: Optional[Dict] = None) -> Dict:
        """执行 5 Agent 流水线。"""
        # 去重
        h = self._chapter_hash(chapter_num, chapter_text)
        if self._is_processed(chapter_num, h):
            self.log(f"[ingest] 第{chapter_num}章已处理，跳过")
            return {"skipped": True, "chapter": chapter_num}

        context = {
            "chapter_num": chapter_num,
            "chapter_text": chapter_text,
            "l3": l3 or {},
            "l1": l1 or {},
            "l2": l2 or {},
            "characters_md": characters_md or "",
        }
        results = {}
        # 1. ChapterScanner
        try:
            results["chapter-scanner"] = await self.agents[0].run(context)
        except Exception as e:
            self._log_error("chapter-scanner", chapter_num, e)
        # 2. EntityExtractor
        try:
            entities = await self.agents[1].run(context)
            results["entity-extractor"] = entities
            context["entities"] = entities
        except Exception as e:
            self._log_error("entity-extractor", chapter_num, e)
        # 3. ForeshadowingTracker
        try:
            results["foreshadowing-tracker"] = await self.agents[2].run(context)
        except Exception as e:
            self._log_error("foreshadowing-tracker", chapter_num, e)
        # 4. CharacterBuilder
        try:
            results["character-builder"] = await self.agents[3].run(context)
        except Exception as e:
            self._log_error("character-builder", chapter_num, e)
        # 5. GraphReviewer
        try:
            results["graph-reviewer"] = await self.agents[4].run(context)
        except Exception as e:
            self._log_error("graph-reviewer", chapter_num, e)

        # 标记已处理
        self._mark_processed(chapter_num, h)
        self.kg.save()
        return {"success": True, "chapter": chapter_num, "results": results}

    def _log_error(self, agent_name: str, chapter_num: int, exc: Exception):
        err_path = os.path.join(self.project_dir, "memory", self.ERROR_LOG)
        os.makedirs(os.path.dirname(err_path), exist_ok=True)
        with open(err_path, "a", encoding="utf-8") as f:
            f.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {agent_name} ch{chapter_num}: {exc}\n")
            f.write(traceback.format_exc() + "\n")


# ============================================================
# 单元测试
# ============================================================

def _self_test():
    import tempfile
    import asyncio
    with tempfile.TemporaryDirectory() as tmp:
        kg = KnowledgeGraph(tmp)
        ip = IngestPipeline(kg, tmp, log=print)

        async def run():
            text = """林轩走进了青云山，拔出寒霜剑，对魔王说："今天我要了结你！"
            战斗持续了百回合，最终林轩收服了寒霜珠。
            """
            r = await ip.ingest_chapter(1, text, l3={"伏笔": "FS-001 埋下"})
            print("First:", r["results"].keys())
            # 再次处理应跳过
            r2 = await ip.ingest_chapter(1, text)
            print("Second:", r2)
        asyncio.run(run())
        st = kg.stats()
        print("Stats:", st)
        assert st["node_count"] >= 3, f"Should have at least 3 nodes, got {st['node_count']}"
        print("Self-test passed!")


if __name__ == "__main__":
    _self_test()
