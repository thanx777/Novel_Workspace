"""知识图谱适配器 — 供 Writer 和 Reviewer 查询 KG 实体，防止幻觉。
同时提供 AI 驱动的摄取功能，从章节/大纲内容中提取实体写入图谱。"""

import asyncio
import json
import os
import re
from typing import Any, Dict, List, Optional


class KGAdapter:
    """封装 KnowledgeGraph 的查询接口，供引擎使用。"""

    def __init__(self, kg=None, project_dir: str = ""):
        self._kg = kg
        self.project_dir = project_dir
        # 并发锁：保护涉及 kg.save() 的异步方法，防止并发写入丢数据
        self._lock = asyncio.Lock()

    @property
    def kg(self):
        """延迟加载 KnowledgeGraph。"""
        if self._kg is None:
            try:
                from knowledge_graph import KnowledgeGraph
                # KnowledgeGraph.__init__ 期望 project_dir，内部会自行拼接
                # memory/knowledge_graph.json，不应传入完整文件路径
                self._kg = KnowledgeGraph(self.project_dir)
            except Exception:
                self._kg = None
        return self._kg

    # ---- 查询 ----

    def get_characters(self) -> List[Dict]:
        """获取所有角色节点。"""
        if not self.kg:
            return []
        return [n for n in self.kg.nodes.values() if n.get("type") == "character"]

    def get_foreshadowings(self) -> List[Dict]:
        """获取所有伏笔节点。"""
        if not self.kg:
            return []
        return [n for n in self.kg.nodes.values() if n.get("type") == "foreshadowing"]

    def get_world_facts(self) -> List[Dict]:
        """获取所有世界观节点。"""
        if not self.kg:
            return []
        return [n for n in self.kg.nodes.values() if n.get("type") == "world_fact"]

    def get_chapters(self) -> List[Dict]:
        """获取所有章节节点（按章号排序）。"""
        if not self.kg:
            return []
        chapters = [n for n in self.kg.nodes.values() if n.get("type") == "chapter"]
        chapters.sort(key=lambda n: n.get("attrs", {}).get("chapter_num", 0))
        return chapters

    def get_outline_nodes(self) -> List[Dict]:
        """获取所有大纲节点。"""
        if not self.kg:
            return []
        return [n for n in self.kg.nodes.values() if n.get("type") == "outline_node"]

    def get_genre_rules(self) -> List[Dict]:
        """获取所有体裁规则节点。"""
        if not self.kg:
            return []
        return [n for n in self.kg.nodes.values() if n.get("type") == "genre_rule"]

    def get_strand_tags(self) -> List[Dict]:
        """获取所有 Strand 标签节点。"""
        if not self.kg:
            return []
        return [n for n in self.kg.nodes.values() if n.get("type") == "strand_tag"]

    def get_coolpoints(self) -> List[Dict]:
        """获取所有爽点事件节点。"""
        if not self.kg:
            return []
        return [n for n in self.kg.nodes.values() if n.get("type") == "coolpoint"]

    def get_hooks(self) -> List[Dict]:
        """获取所有钩子事件节点。"""
        if not self.kg:
            return []
        return [n for n in self.kg.nodes.values() if n.get("type") == "hook"]

    def get_character_relationships(self) -> List[Dict]:
        """获取所有角色关系边。"""
        if not self.kg:
            return []
        return [e for e in self.kg.edges.values() if e.get("type") == "relates_to"]

    def get_active_foreshadowings(self, up_to_chapter: int = 999) -> List[Dict]:
        """获取活跃伏笔（已埋设但未回收的）。"""
        all_fs = self.get_foreshadowings()
        active = []
        for fs in all_fs:
            attrs = fs.get("attrs", {})
            status = attrs.get("status", "")
            ch_buried = attrs.get("buried_chapter", 0)
            if status in ("buried", "active", "") and ch_buried <= up_to_chapter:
                active.append(fs)
        return active

    # ---- 上下文格式化 ----

    def format_character_context(self) -> str:
        """格式化角色信息，供 Writer prompt 注入。"""
        chars = self.get_characters()
        if not chars:
            return ""
        lines = ["【知识图谱 · 角色列表（禁止凭空编造新角色）】"]
        for c in chars:
            label = c.get("label", "")
            summary = c.get("summary", "")
            lines.append(f"- {label}：{summary}" if summary else f"- {label}")
        return "\n".join(lines)

    def format_foreshadowing_context(self) -> str:
        """格式化伏笔信息。"""
        fs_list = self.get_foreshadowings()
        if not fs_list:
            return ""
        lines = ["【知识图谱 · 伏笔清单（必须按计划埋设/回收）】"]
        for fs in fs_list:
            label = fs.get("label", "")
            summary = fs.get("summary", "")
            attrs = fs.get("attrs", {})
            status = attrs.get("status", "unknown")
            lines.append(f"- {label}（{status}）：{summary}" if summary else f"- {label}（{status}）")
        return "\n".join(lines)

    def format_world_context(self) -> str:
        """格式化世界观信息。"""
        facts = self.get_world_facts()
        if not facts:
            return ""
        lines = ["【知识图谱 · 世界观（禁止凭空编造新设定）】"]
        for f in facts:
            label = f.get("label", "")
            summary = f.get("summary", "")
            lines.append(f"- {label}：{summary}" if summary else f"- {label}")
        return "\n".join(lines)

    def format_outline_context(self) -> str:
        """格式化大纲节点信息。"""
        nodes = self.get_outline_nodes()
        if not nodes:
            return ""
        lines = ["【知识图谱 · 大纲节点】"]
        for n in nodes:
            label = n.get("label", "")
            summary = n.get("summary", "")
            lines.append(f"- {label}：{summary}" if summary else f"- {label}")
        return "\n".join(lines)

    def format_scene_context(self) -> str:
        """格式化场景信息。"""
        if not self.kg:
            return ""
        scenes = [n for n in self.kg.nodes.values() if n.get("type") == "scene"]
        if not scenes:
            return ""
        lines = ["【知识图谱 · 场景（写作时场景必须与已有场景一致）】"]
        for s in scenes:
            label = s.get("label", "")
            summary = s.get("summary", "")
            lines.append(f"- {label}：{summary}" if summary else f"- {label}")
        return "\n".join(lines)

    def format_plot_thread_context(self) -> str:
        """格式化剧情线信息。"""
        if not self.kg:
            return ""
        threads = [n for n in self.kg.nodes.values() if n.get("type") == "plot_thread"]
        if not threads:
            return ""
        lines = ["【知识图谱 · 剧情线（必须推进已有剧情线，禁止遗忘）】"]
        for t in threads:
            label = t.get("label", "")
            summary = t.get("summary", "")
            attrs = t.get("attrs", {})
            chars = attrs.get("characters", [])
            char_str = f"（涉及：{'、'.join(chars)}）" if chars else ""
            lines.append(f"- {label}{char_str}：{summary}" if summary else f"- {label}{char_str}")
        return "\n".join(lines)

    def format_strand_context(self) -> str:
        """格式化 Strand 节奏标签。"""
        tags = self.get_strand_tags()
        if not tags:
            return ""
        lines = ["【知识图谱 · Strand 节奏记录】"]
        for t in tags:
            attrs = t.get("attrs", {})
            ch = attrs.get("chapter_num", "?")
            strand_type = attrs.get("strand_type", "")
            lines.append(f"- 第{ch}章：{strand_type}")
        return "\n".join(lines)

    def format_coolpoint_context(self) -> str:
        """格式化爽点事件。"""
        cps = self.get_coolpoints()
        if not cps:
            return ""
        lines = ["【知识图谱 · 爽点记录（参考已有爽点，避免重复）】"]
        for cp in cps:
            attrs = cp.get("attrs", {})
            ch = attrs.get("chapter_num", "?")
            cp_type = attrs.get("coolpoint_type", "")
            lines.append(f"- 第{ch}章：{cp_type} — {cp.get('summary', '')}")
        return "\n".join(lines)

    def format_hook_context(self) -> str:
        """格式化钩子事件。"""
        hooks = self.get_hooks()
        if not hooks:
            return ""
        lines = ["【知识图谱 · 钩子记录（章末悬念追踪）】"]
        for h in hooks:
            attrs = h.get("attrs", {})
            ch = attrs.get("chapter_num", "?")
            hook_type = attrs.get("hook_type", "")
            resolved = attrs.get("resolved", False)
            status = "已回应" if resolved else "待回应"
            lines.append(f"- 第{ch}章 {hook_type}（{status}）：{h.get('summary', '')}")
        return "\n".join(lines)

    def format_relationship_context(self) -> str:
        """格式化角色关系。"""
        rels = self.get_character_relationships()
        if not rels:
            return ""
        lines = ["【知识图谱 · 角色关系网】"]
        for r in rels:
            source = r.get("source", "")
            target = r.get("target", "")
            attrs = r.get("attrs", {})
            rel_type = attrs.get("relation", "")
            # 从节点 ID 提取名字
            s_name = source.replace("char_", "")
            t_name = target.replace("char_", "")
            lines.append(f"- {s_name} → {t_name}：{rel_type}")
        return "\n".join(lines)

    def _format_previous_chapters(self, chapter_num: int) -> str:
        """格式化前 N-1 章的摘要，供当前章参考。包含所有前章摘要（每章仅1行，与 KG 其他全局信息保持一致）。"""
        if not self.kg or chapter_num <= 1:
            return ""
        prev_chapters = []
        for n in self.kg.nodes.values():
            if n.get("type") == "chapter":
                attrs = n.get("attrs", {})
                ch_num = attrs.get("chapter_num", 0)
                if 0 < ch_num < chapter_num:
                    prev_chapters.append((ch_num, n))
        if not prev_chapters:
            return ""
        prev_chapters.sort(key=lambda x: x[0])
        # 包含所有前章摘要（每章仅1行，120章也只有120行，与 KG 其他全局信息保持一致）
        lines = [f"【知识图谱 · 前情提要（第{prev_chapters[0][0]}-{prev_chapters[-1][0]}章）】"]
        for ch_num, node in prev_chapters:
            label = node.get("label", f"第{ch_num}章")
            summary = node.get("summary", "")
            lines.append(f"- {label}：{summary}" if summary else f"- {label}")
        return "\n".join(lines)

    def get_chapter_context(self, chapter_num: int) -> str:
        """获取写第 N 章需要的完整 KG 上下文（角色+伏笔+世界观+场景+剧情线+节奏+爽点+钩子+关系）。"""
        parts = []
        chars = self.format_character_context()
        if chars:
            parts.append(chars)
        fs = self.format_foreshadowing_context()
        if fs:
            parts.append(fs)
        world = self.format_world_context()
        if world:
            parts.append(world)
        # 场景
        scenes = self.format_scene_context()
        if scenes:
            parts.append(scenes)
        # 剧情线
        threads = self.format_plot_thread_context()
        if threads:
            parts.append(threads)
        # 角色关系网
        rels = self.format_relationship_context()
        if rels:
            parts.append(rels)
        # Strand 节奏记录
        strand = self.format_strand_context()
        if strand:
            parts.append(strand)
        # 爽点记录
        coolpoints = self.format_coolpoint_context()
        if coolpoints:
            parts.append(coolpoints)
        # 钩子记录
        hooks = self.format_hook_context()
        if hooks:
            parts.append(hooks)
        # 前情提要（该章之前的章节节点）
        prev = self._format_previous_chapters(chapter_num)
        if prev:
            parts.append(prev)
        return "\n\n".join(parts)

    def get_outline_layer_context(self, layer: str) -> str:
        """获取大纲生成时需要的 KG 上下文（L1 不需要，L2/L3 需要）。"""
        if layer == "L1":
            return ""
        parts = []
        chars = self.format_character_context()
        if chars:
            parts.append(chars)
        fs = self.format_foreshadowing_context()
        if fs:
            parts.append(fs)
        world = self.format_world_context()
        if world:
            parts.append(world)
        scenes = self.format_scene_context()
        if scenes:
            parts.append(scenes)
        outline = self.format_outline_context()
        if outline:
            parts.append(outline)
        return "\n\n".join(parts)

    # ---- 幻觉检测 ----

    def validate_character_names(self, names: List[str]) -> List[str]:
        """检查人名是否都在 KG 中存在。返回不在 KG 中的名字。"""
        kg_names = set()
        for c in self.get_characters():
            label = c.get("label", "")
            # 提取纯名字（去掉"角色："前缀等）
            pure_name = label.split("：")[-1].split(":")[-1].strip()
            if pure_name:
                kg_names.add(pure_name)
        unknown = []
        for name in names:
            if name and name not in kg_names:
                unknown.append(name)
        return unknown

    def validate_foreshadowing_ids(self, fs_ids: List[str]) -> List[str]:
        """检查伏笔 ID 是否在 KG 中存在。"""
        kg_ids = set()
        for fs in self.get_foreshadowings():
            label = fs.get("label", "")
            # 提取 FS-XXX
            import re
            for m in re.finditer(r"FS-\d+", label):
                kg_ids.add(m.group())
        unknown = []
        for fid in fs_ids:
            if fid and fid not in kg_ids:
                unknown.append(fid)
        return unknown

    # ---- 写入 ----

    def add_chapter_node(self, chapter_num: int, title: str, summary: str = ""):
        """写完一章后添加/更新章节节点。"""
        if not self.kg:
            return
        node_id = f"chapter_{chapter_num}"
        self.kg.add_node(node_id, "chapter", f"第{chapter_num}章 {title}",
                         summary=summary,
                         attrs={"chapter_num": chapter_num, "title": title})
        self.kg.save()

    def update_foreshadowing_status(self, fs_id: str, status: str, chapter_num: int = 0):
        """更新伏笔状态（buried → active → resolved）。"""
        if not self.kg:
            return
        for node in self.kg.nodes.values():
            if fs_id in node.get("label", ""):
                node.setdefault("attrs", {})["status"] = status
                if chapter_num:
                    if status == "buried":
                        node["attrs"]["buried_chapter"] = chapter_num
                    elif status == "resolved":
                        node["attrs"]["resolved_chapter"] = chapter_num
                break
        self.kg.save()

    # ---- AI 驱动摄取 ----

    async def ai_ingest_chapter(self, chapter_num: int, chapter_text: str,
                                 llm_client=None, emit=None) -> Dict:
        """AI 驱动的章节摄取：提取角色/伏笔/场景/世界观/剧情线，写入图谱。

        Args:
            chapter_num: 章节号
            chapter_text: 章节正文
            llm_client: LLMClient 实例（用于调用 AI）
            emit: 事件回调

        Returns:
            摄取结果统计
        """
        if not self.kg or not chapter_text:
            return {"skipped": True, "reason": "no kg or no text"}

        if emit:
            emit({"status": "kg_ingesting", "chapter": chapter_num, "message": f"AI 正在摄取第{chapter_num}章到知识图谱..."})

        # 并发锁保护：防止多章并发摄取时 KG 数据丢失
        async with self._lock:
            # 先添加章节节点（基础信息）
            title = ""
            title_match = re.search(r"第\d+章[：:\s]*(.+?)[\n\r]", chapter_text)
            if title_match:
                title = title_match.group(1).strip()
            self.add_chapter_node(chapter_num, title, chapter_text[:200])

            # 如果没有 LLM，用规则 fallback
            if not llm_client or not llm_client.has_valid_config("reviewer"):
                if emit:
                    emit({"status": "kg_ingest_fallback", "chapter": chapter_num, "message": "无 AI 配置，使用规则摄取"})
                return self._rule_ingest_chapter(chapter_num, chapter_text)

            # AI 摄取
            from .prompts import KG_INGEST_SYSTEM

            # 构建已有 KG 上下文，让 AI 知道哪些实体已存在
            existing_context = self._format_existing_entities()

            user_prompt = f"请从以下章节内容中提取实体，更新知识图谱。\n\n"
            if existing_context:
                user_prompt += f"【已有知识图谱实体（已存在的不要重复创建，只更新状态）】\n{existing_context}\n\n"
            user_prompt += f"--- 第{chapter_num}章正文 ---\n{chapter_text[:8000]}\n--- 正文结束 ---"

            try:
                response = await llm_client.call("reviewer", KG_INGEST_SYSTEM, user_prompt)
                entities = self._parse_ingest_response(response)
                stats = self._write_entities_to_kg(entities, chapter_num)
                if emit:
                    emit({"status": "kg_ingested", "chapter": chapter_num, **stats})
                return {"success": True, "chapter": chapter_num, **stats}
            except Exception as e:
                if emit:
                    emit({"status": "kg_ingest_error", "chapter": chapter_num, "error": str(e)})
                # fallback 到规则摄取
                return self._rule_ingest_chapter(chapter_num, chapter_text)

    async def ai_ingest_outline(self, layer: str, outline_text: str,
                                 json_data: Dict = None,
                                 llm_client=None, emit=None) -> Dict:
        """AI 驱动的大纲摄取：从大纲中提取实体初始化图谱。

        Args:
            layer: 大纲层级 (L1/L2/L3)
            outline_text: 大纲 markdown 文本
            json_data: 解析后的 JSON 数据
            llm_client: LLMClient 实例
            emit: 事件回调
        """
        if not self.kg or not outline_text:
            return {"skipped": True, "reason": "no kg or no text"}

        if emit:
            emit({"status": "kg_ingesting_outline", "layer": layer, "message": f"AI 正在摄取{layer}大纲到知识图谱..."})

        # 并发锁保护：防止并发摄取时 KG 数据丢失
        async with self._lock:
            # 先添加大纲节点
            from .prompts import LAYER_NAMES
            node_id = f"outline_{layer}_root"
            self.kg.add_node(node_id, "outline_node",
                             LAYER_NAMES.get(layer, layer),
                             summary=outline_text[:500],
                             attrs={"layer": layer})
            if layer == "L2":
                l1_id = "outline_L1_root"
                if l1_id in self.kg.nodes:
                    self.kg.add_edge("edge_L2_from_L1", "derived_from", node_id, l1_id)
            self.kg.save()

            # 如果没有 LLM，只写入大纲节点
            if not llm_client or not llm_client.has_valid_config("reviewer"):
                return {"success": True, "layer": layer, "outline_node": True, "entities": "no_llm"}

            from .prompts import KG_INGEST_OUTLINE_SYSTEM

            existing_context = self._format_existing_entities()
            user_prompt = f"请从以下{layer}大纲中提取实体，初始化知识图谱。\n\n"
            if existing_context:
                user_prompt += f"【已有知识图谱实体】\n{existing_context}\n\n"
            user_prompt += f"--- {layer}大纲 ---\n{outline_text[:8000]}\n--- 大纲结束 ---"

            try:
                response = await llm_client.call("reviewer", KG_INGEST_OUTLINE_SYSTEM, user_prompt)
                entities = self._parse_ingest_response(response)
                stats = self._write_entities_to_kg(entities, chapter_num=0)
                if emit:
                    emit({"status": "kg_outline_ingested", "layer": layer, **stats})
                return {"success": True, "layer": layer, "outline_node": True, **stats}
            except Exception as e:
                if emit:
                    emit({"status": "kg_ingest_error", "layer": layer, "error": str(e)})
                return {"success": True, "layer": layer, "outline_node": True, "entities": "error"}

    # ---- 内部方法 ----

    def _format_existing_entities(self, max_per_type: int = 20) -> str:
        """格式化已有 KG 实体，供 AI 参考避免重复。

        Args:
            max_per_type: 每类实体最多显示的数量（防止 prompt 过长）
        """
        if not self.kg:
            return ""
        lines = []

        def _truncate(items, formatter):
            """截断实体列表，超过 max_per_type 时只显示前 N 个并标注总数。"""
            if not items:
                return None
            if len(items) <= max_per_type:
                return formatter(items)
            shown = items[:max_per_type]
            return f"{formatter(shown)} 等{len(items)}个"

        chars = self.get_characters()
        if chars:
            s = _truncate(chars, lambda cs: "、".join(c.get("label", "") for c in cs))
            if s:
                lines.append("已有角色：" + s)
        fs = self.get_foreshadowings()
        if fs:
            s = _truncate(fs, lambda fsl: "、".join(f.get("label", "") for f in fsl))
            if s:
                lines.append("已有伏笔：" + s)
        scenes = [n for n in self.kg.nodes.values() if n.get("type") == "scene"]
        if scenes:
            s = _truncate(scenes, lambda ss: "、".join(s.get("label", "") for s in ss))
            if s:
                lines.append("已有场景：" + s)
        facts = self.get_world_facts()
        if facts:
            s = _truncate(facts, lambda fs: "、".join(f.get("label", "") for f in fs))
            if s:
                lines.append("已有世界观：" + s)
        threads = [n for n in self.kg.nodes.values() if n.get("type") == "plot_thread"]
        if threads:
            s = _truncate(threads, lambda ts: "、".join(t.get("label", "") for t in ts))
            if s:
                lines.append("已有剧情线：" + s)
        # 新增：角色关系
        rels = self.get_character_relationships()
        if rels:
            def _fmt_rels(rs):
                rel_strs = []
                for r in rs:
                    s_name = r.get("source", "").replace("char_", "")
                    t_name = r.get("target", "").replace("char_", "")
                    rel_type = r.get("attrs", {}).get("relation", "")
                    rel_strs.append(f"{s_name}→{t_name}({rel_type})")
                return "、".join(rel_strs)
            s = _truncate(rels, _fmt_rels)
            if s:
                lines.append("已有角色关系：" + s)
        # 新增：Strand 标签
        strands = self.get_strand_tags()
        if strands:
            s = _truncate(strands, lambda ss: "、".join(
                f"第{s.get('attrs', {}).get('chapter_num', '?')}章:{s.get('attrs', {}).get('strand_type', '')}" for s in ss
            ))
            if s:
                lines.append("已有Strand标签：" + s)
        # 新增：爽点
        cps = self.get_coolpoints()
        if cps:
            s = _truncate(cps, lambda cs: "、".join(
                f"第{c.get('attrs', {}).get('chapter_num', '?')}章:{c.get('attrs', {}).get('coolpoint_type', '')}" for c in cs
            ))
            if s:
                lines.append("已有爽点：" + s)
        # 新增：钩子
        hooks = self.get_hooks()
        if hooks:
            s = _truncate(hooks, lambda hs: "、".join(
                f"第{h.get('attrs', {}).get('chapter_num', '?')}章:{h.get('attrs', {}).get('hook_type', '')}" for h in hs
            ))
            if s:
                lines.append("已有钩子：" + s)
        return "\n".join(lines)

    def _parse_ingest_response(self, response: str) -> Dict:
        """解析 AI 摄取响应，提取 JSON。"""
        # 尝试直接解析
        try:
            data = json.loads(response)
            return self._normalize_ingest_data(data)
        except json.JSONDecodeError:
            pass
        # 尝试提取 ```json ... ``` 块（贪婪匹配，支持嵌套JSON）
        m = re.search(r"```(?:json)?\s*(\{.+\})\s*```", response, re.DOTALL)
        if m:
            try:
                data = json.loads(m.group(1))
                return self._normalize_ingest_data(data)
            except json.JSONDecodeError:
                pass
        # 尝试找到第一个 { ... } 块（贪婪匹配）
        m = re.search(r"\{[\s\S]+\}", response)
        if m:
            try:
                data = json.loads(m.group())
                return self._normalize_ingest_data(data)
            except json.JSONDecodeError:
                pass
        return {}

    def _normalize_ingest_data(self, data: Dict) -> Dict:
        """规范化 LLM 返回的摄取数据，兼容不同的 key 命名。

        LLM 可能返回：
        - {"characters": [...], "foreshadowings": [...]}  （期望格式）
        - {"entities": {"character": [...], "foreshadowing": [...]}}  （嵌套格式）
        """
        if not isinstance(data, dict):
            return data
        # 如果顶层有 entities 键，提取其内容
        if "entities" in data and isinstance(data["entities"], dict):
            entities = data["entities"]
            # 映射单数 key 到复数 key
            key_map = {
                "character": "characters",
                "foreshadowing": "foreshadowings",
                "scene": "scenes",
                "world_fact": "world_facts",
                "plot_thread": "plot_threads",
                "relationship": "relationships",
                "strand": "strand_tags",
                "coolpoint": "coolpoints",
                "hook": "hooks",
            }
            result = {}
            for k, v in entities.items():
                mapped_key = key_map.get(k, k)
                result[mapped_key] = v
            return result
        return data

    def _write_entities_to_kg(self, entities: Dict, chapter_num: int = 0) -> Dict:
        """将解析出的实体写入知识图谱。"""
        if not self.kg:
            return {}
        stats = {"characters": 0, "foreshadowings": 0, "scenes": 0, "world_facts": 0, "plot_threads": 0,
                 "relationships": 0, "strand_tags": 0, "coolpoints": 0, "hooks": 0}

        # 角色
        for ch in entities.get("characters", []):
            name = ch.get("name", "").strip()
            if not name:
                continue
            nid = f"char_{name}"
            summary = f"{ch.get('identity', '')} {ch.get('status', '')}".strip()
            attrs = {
                "identity": ch.get("identity", ""),
                "status": ch.get("status", ""),
                "relations": ch.get("relations", []),
            }
            if chapter_num:
                attrs["latest_chapter"] = chapter_num
                existing = self.kg.get_node(nid)
                if existing:
                    appearances = existing.get("attrs", {}).get("appearances", [])
                    if chapter_num not in appearances:
                        appearances.append(chapter_num)
                    attrs["appearances"] = appearances
                else:
                    attrs["appearances"] = [chapter_num]

            self.kg.add_node(nid, "character", name, summary=summary or name, attrs=attrs)
            if chapter_num:
                self.kg.add_edge(f"edge_{nid}_ch{chapter_num}", "appears_in", nid, f"chapter_{chapter_num}",
                                 attrs={"chapter_num": chapter_num})
            stats["characters"] += 1

        # 伏笔
        for fs in entities.get("foreshadowings", []):
            fs_id = fs.get("id", "").strip()
            desc = fs.get("description", "").strip()
            if not fs_id:
                continue
            nid = f"foreshadowing_{fs_id}"
            status = fs.get("status", "buried")
            attrs = {"status": status}
            if chapter_num:
                if status == "buried":
                    attrs["buried_chapter"] = chapter_num
                elif status == "resolved":
                    attrs["resolved_chapter"] = chapter_num
                    existing = self.kg.get_node(nid)
                    if existing:
                        attrs["buried_chapter"] = existing.get("attrs", {}).get("buried_chapter", 0)

            self.kg.add_node(nid, "foreshadowing", fs_id,
                             summary=desc or f"伏笔 {fs_id}", attrs=attrs)
            if chapter_num:
                action = "pay_off" if status == "resolved" else "set"
                self.kg.add_edge(f"edge_{nid}_{action}_ch{chapter_num}",
                                 "belongs_to", nid, f"chapter_{chapter_num}",
                                 attrs={"action": action, "chapter_num": chapter_num})
            stats["foreshadowings"] += 1

        # 场景
        for sc in entities.get("scenes", []):
            name = sc.get("name", "").strip()
            if not name:
                continue
            nid = f"scene_{name}"
            attrs = {"type": sc.get("type", ""), "description": sc.get("description", "")}
            if chapter_num:
                attrs["first_chapter"] = chapter_num
            self.kg.add_node(nid, "scene", name,
                             summary=sc.get("description", name), attrs=attrs)
            if chapter_num:
                self.kg.add_edge(f"edge_{nid}_ch{chapter_num}", "happens_in", nid, f"chapter_{chapter_num}",
                                 attrs={"chapter_num": chapter_num})
            stats["scenes"] += 1

        # 世界观
        for wf in entities.get("world_facts", []):
            name = wf.get("name", "").strip()
            if not name:
                continue
            nid = f"world_{name}"
            self.kg.add_node(nid, "world_fact", name,
                             summary=wf.get("description", name),
                             attrs={"description": wf.get("description", "")})
            stats["world_facts"] += 1

        # 剧情线
        for pt in entities.get("plot_threads", []):
            name = pt.get("name", "").strip()
            if not name:
                continue
            nid = f"thread_{name}"
            attrs = {
                "progress": pt.get("progress", ""),
                "characters": pt.get("characters", []),
            }
            if chapter_num:
                attrs["latest_chapter"] = chapter_num
            self.kg.add_node(nid, "plot_thread", name,
                             summary=pt.get("progress", name), attrs=attrs)
            stats["plot_threads"] += 1

        # 角色关系（新增）
        for rel in entities.get("relationships", []):
            source = rel.get("source", "").strip()
            target = rel.get("target", "").strip()
            relation = rel.get("relation", "").strip()
            if not source or not target or not relation:
                continue
            s_nid = f"char_{source}"
            t_nid = f"char_{target}"
            # 确保两个角色节点存在
            if s_nid not in self.kg.nodes:
                self.kg.add_node(s_nid, "character", source, summary=source)
            if t_nid not in self.kg.nodes:
                self.kg.add_node(t_nid, "character", target, summary=target)
            # 添加关系边
            edge_id = f"rel_{source}_{target}"
            self.kg.add_edge(edge_id, "relates_to", s_nid, t_nid,
                             attrs={"relation": relation, "chapter_num": chapter_num})
            stats["relationships"] += 1

        # Strand 标签（新增）
        strand = entities.get("strand", "").strip()
        if strand and chapter_num:
            nid = f"strand_ch{chapter_num}"
            self.kg.add_node(nid, "strand_tag", f"第{chapter_num}章·{strand}",
                             summary=f"第{chapter_num}章节奏类型：{strand}",
                             attrs={"chapter_num": chapter_num, "strand_type": strand})
            # 章节被标注为该 Strand 类型
            self.kg.add_edge(f"edge_strand_ch{chapter_num}", "tagged_as",
                             f"chapter_{chapter_num}", nid,
                             attrs={"strand_type": strand})
            stats["strand_tags"] += 1

        # 爽点事件（新增）
        for cp in entities.get("coolpoints", []):
            cp_type = cp.get("type", "").strip()
            cp_desc = cp.get("description", "").strip()
            if not cp_type:
                continue
            nid = f"coolpoint_ch{chapter_num}_{cp_type}"
            self.kg.add_node(nid, "coolpoint", f"第{chapter_num}章·{cp_type}",
                             summary=cp_desc or cp_type,
                             attrs={"chapter_num": chapter_num, "coolpoint_type": cp_type})
            # 爽点属于某章节
            if chapter_num:
                self.kg.add_edge(f"edge_{nid}_ch{chapter_num}", "belongs_to",
                                 nid, f"chapter_{chapter_num}",
                                 attrs={"chapter_num": chapter_num})
            # 爽点可能兑现伏笔
            for fs in entities.get("foreshadowings", []):
                if fs.get("status") == "resolved":
                    fs_id = fs.get("id", "")
                    if fs_id:
                        self.kg.add_edge(f"edge_{nid}_payoff_{fs_id}", "pays_off",
                                         nid, f"foreshadowing_{fs_id}")
            stats["coolpoints"] += 1

        # 钩子事件（新增）
        for hk in entities.get("hooks", []):
            hk_type = hk.get("type", "").strip()
            hk_desc = hk.get("description", "").strip()
            if not hk_type:
                continue
            nid = f"hook_ch{chapter_num}_{hk_type}"
            self.kg.add_node(nid, "hook", f"第{chapter_num}章·{hk_type}",
                             summary=hk_desc or hk_type,
                             attrs={"chapter_num": chapter_num, "hook_type": hk_type, "resolved": False})
            # 钩子属于某章节
            if chapter_num:
                self.kg.add_edge(f"edge_{nid}_ch{chapter_num}", "belongs_to",
                                 nid, f"chapter_{chapter_num}",
                                 attrs={"chapter_num": chapter_num})
            stats["hooks"] += 1

        self.kg.save()
        return stats

    def _rule_ingest_chapter(self, chapter_num: int, chapter_text: str) -> Dict:
        """规则 fallback 摄取（无 AI 时使用）。"""
        stats = {"characters": 0, "foreshadowings": 0, "scenes": 0, "world_facts": 0, "plot_threads": 0}
        if not self.kg:
            return stats

        # 提取人名（"XX说道"模式）
        names = set()
        for m in re.finditer(r"[\u4e00-\u9fff]{2,4}(?=说道|道|喊|叫|笑|怒|叹|想|问|答)", chapter_text):
            name = m.group()
            if len(name) >= 2:
                names.add(name)
        for name in names:
            nid = f"char_{name}"
            existing = self.kg.get_node(nid)
            attrs = {}
            if existing:
                appearances = existing.get("attrs", {}).get("appearances", [])
                if chapter_num not in appearances:
                    appearances.append(chapter_num)
                attrs["appearances"] = appearances
            else:
                attrs["appearances"] = [chapter_num]
            attrs["latest_chapter"] = chapter_num
            self.kg.add_node(nid, "character", name,
                             summary=existing.get("summary", f"第{chapter_num}章首次提及") if existing else f"第{chapter_num}章首次提及",
                             attrs=attrs)
            self.kg.add_edge(f"edge_{nid}_ch{chapter_num}", "appears_in", nid, f"chapter_{chapter_num}",
                             attrs={"chapter_num": chapter_num})
            stats["characters"] += 1

        # 提取伏笔 ID
        for fs_id in set(re.findall(r"FS-\d+", chapter_text)):
            nid = f"foreshadowing_{fs_id}"
            existing = self.kg.get_node(nid)
            if existing:
                # 更新出场
                continue
            self.kg.add_node(nid, "foreshadowing", fs_id,
                             summary=f"伏笔 {fs_id}",
                             attrs={"status": "buried", "buried_chapter": chapter_num})
            self.kg.add_edge(f"edge_{nid}_set_ch{chapter_num}", "belongs_to", nid, f"chapter_{chapter_num}",
                             attrs={"action": "set", "chapter_num": chapter_num})
            stats["foreshadowings"] += 1

        # 提取场景（简单正则）
        loc_suffix = r"山|城|镇|村|谷|派|门|教|宫|殿|阁"
        for loc in set(re.findall(rf"[\u4e00-\u9fff]{{1,4}}(?:{loc_suffix})", chapter_text)):
            nid = f"scene_{loc}"
            if nid not in self.kg.nodes:
                self.kg.add_node(nid, "scene", loc,
                                 summary=f"第{chapter_num}章出现",
                                 attrs={"first_chapter": chapter_num})
                self.kg.add_edge(f"edge_{nid}_ch{chapter_num}", "happens_in", nid, f"chapter_{chapter_num}",
                                 attrs={"chapter_num": chapter_num})
                stats["scenes"] += 1

        self.kg.save()
        return {"success": True, "chapter": chapter_num, "mode": "rule", **stats}
