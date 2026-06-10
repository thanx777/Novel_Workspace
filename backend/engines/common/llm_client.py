"""LLM 客户端 — 项目级 AI 配置解析、角色级覆盖、fallback。"""

import os
from typing import Any, Dict, List, Optional

# 复用现有 executor 的 call_llm 和 AgentConfig
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from executor import AgentConfig, call_llm


# 角色默认参数
ROLE_DEFAULTS = {
    "manager":  {"temperature": 0.3, "max_tokens": 1000},
    "writer":   {"temperature": 0.7, "max_tokens": 8000},
    "reviewer": {"temperature": 0.2, "max_tokens": 2000},
}


class LLMClient:
    """统一 LLM 调用，支持项目级 preset + 角色级覆盖。"""

    def __init__(self, project_presets: Optional[Dict[str, Dict]] = None,
                 global_presets: Optional[List[Dict]] = None):
        """
        Args:
            project_presets: 项目级角色预设 {"manager": {...}, "writer": {...}, "reviewer": {...}, "chat": {...}}
            global_presets: 全局预设列表（fallback）
        """
        self.project_presets = project_presets or {}
        self.global_presets = global_presets or []

    def resolve_config(self, role: str) -> AgentConfig:
        """按角色解析最终 LLM 配置。

        优先级：project_presets[role] > project_presets["chat"] > global_presets[0] > 默认
        """
        preset = self._find_preset(role)
        if preset is None:
            # 无任何配置，返回一个空 AgentConfig（会触发 fallback）
            return AgentConfig(
                api_key="",
                base_url="https://integrate.api.nvidia.com/v1",
                model="meta/llama-4-maverick-17b-128e-instruct",
                api_format="openai",
            )

        cfg = AgentConfig(
            api_key=preset.get("api_key", ""),
            base_url=preset.get("base_url", "https://integrate.api.nvidia.com/v1"),
            model=preset.get("model", ""),
            api_format=preset.get("api_format", "openai"),
            chat_template_kwargs=preset.get("chat_template_kwargs"),
            thinking_mode=preset.get("thinking_mode"),
        )
        return cfg

    def _find_preset(self, role: str) -> Optional[Dict]:
        """按优先级查找 preset。"""
        # 1. 项目级角色预设
        role_key = f"{role}_preset" if not role.endswith("_preset") else role
        p = self.project_presets.get(role) or self.project_presets.get(role_key)
        if p and isinstance(p, dict) and p.get("api_key"):
            return p
        # 2. 项目级 chat preset（通用）
        p = self.project_presets.get("chat") or self.project_presets.get("chat_preset")
        if p and isinstance(p, dict) and p.get("api_key"):
            return p
        # 3. 全局 presets[0]
        if self.global_presets:
            for gp in self.global_presets:
                if isinstance(gp, dict) and gp.get("api_key"):
                    return gp
        return None

    async def call(self, role: str, system_prompt: str, user_prompt: str,
                   max_tokens: Optional[int] = None,
                   request_timeout_seconds: int = 300) -> str:
        """调用 LLM，自动按角色解析配置。"""
        cfg = self.resolve_config(role)
        if not cfg.api_key:
            return "[LLM_ERROR: 未配置 API Key]"

        # 角色默认参数
        defaults = ROLE_DEFAULTS.get(role, {})
        mt = max_tokens or defaults.get("max_tokens", 4000)

        text = await call_llm(cfg, system_prompt, user_prompt,
                              max_tokens=mt,
                              request_timeout_seconds=request_timeout_seconds)
        if not text or text.startswith("[LLM_ERROR"):
            return text or "[LLM_ERROR: 空响应]"
        return text

    def has_valid_config(self, role: str = "writer") -> bool:
        """检查是否有可用的 LLM 配置。"""
        p = self._find_preset(role)
        return p is not None and bool(p.get("api_key"))
