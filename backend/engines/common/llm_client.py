"""LLM 客户端 — AgentConfig、call_llm、is_llm_error 定义 + 项目级 AI 配置解析、角色级覆盖、fallback。

从 executor.py 迁移而来，消除对旧引擎的依赖。
"""

import httpx
from typing import Any, Dict, List, Optional
from pydantic import BaseModel
from openai import AsyncOpenAI


# ============================================
# AgentConfig — LLM 配置模型
# ============================================

class AgentConfig(BaseModel):
    api_key: str
    base_url: str = "https://open.bigmodel.cn/api/paas/v4"
    model: str = "glm-4-flash"
    api_format: str = "openai"
    chat_template_kwargs: Optional[dict] = None
    thinking_mode: Optional[str] = None  # "enabled" | "disabled" | None (仅 DeepSeek 等支持思考模式的模型)


# ============================================
# call_llm — 统一 LLM 调用
# ============================================

async def call_llm(
    config: AgentConfig,
    system_prompt: str,
    user_prompt: str,
    max_tokens: int,
    request_timeout_seconds: float,
):
    api_key = config.api_key.strip()
    base_url = config.base_url.strip().strip("`").strip()
    model = config.model.strip()
    api_format = getattr(config, "api_format", "openai")

    if not api_key:
        return "Error: API Key 未配置"
    if not base_url or not model:
        return "Error: Base URL 或模型名未配置"
    try:
        if api_format == "claude":
            headers = {
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json"
            }

            payload = {
                "model": model,
                "max_tokens": max_tokens,
                "messages": [
                    {"role": "user", "content": f"{system_prompt}\n\n{user_prompt}"}
                ],
                "temperature": 0.7
            }

            async with httpx.AsyncClient(timeout=request_timeout_seconds) as client:
                response = await client.post(base_url, json=payload, headers=headers)

            if response.status_code != 200:
                return f"Error: {response.status_code} - {response.text[:500]}"

            result = response.json()
            full_content = result.get("content", [{}])[0].get("text", "")

        else:
            client = AsyncOpenAI(api_key=api_key, base_url=base_url, timeout=request_timeout_seconds, max_retries=0)
            kwargs = {
                "model": model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                "temperature": 0.7,
                "max_tokens": max_tokens
            }

            if config.chat_template_kwargs:
                kwargs["extra_body"] = {"chat_template_kwargs": config.chat_template_kwargs}
            elif "nvidia.com" in base_url:
                kwargs["extra_body"] = {"chat_template_kwargs": {"thinking": False}}
            elif "deepseek.com" in base_url:
                mode = getattr(config, "thinking_mode", None) or "disabled"
                kwargs["extra_body"] = {"thinking": {"type": mode}}
            kwargs["stream"] = False

            response = await client.chat.completions.create(**kwargs)

            full_content = ""
            if response.choices and response.choices[0].message:
                msg = response.choices[0].message
                full_content = msg.content or ""
                if not full_content.strip() and getattr(msg, "reasoning_content", None):
                    full_content = msg.reasoning_content or ""

        if not full_content.strip():
            return "Error: 模型返回为空，可能是当前模型不支持该请求格式"
        return full_content
    except Exception as e:
        error_msg = str(e)
        if "timed out" in error_msg.lower():
            if "nvidia.com" in base_url:
                return f"Error: NVIDIA API 超时。建议尝试更快的模型或减少任务复杂度"
            return f"Error: 请求超时"
        elif "401" in error_msg or "api_key" in error_msg.lower():
            return f"Error: API Key 无效或认证失败"
        elif "403" in error_msg:
            return f"Error: 访问被拒绝"
        elif "404" in error_msg or "not found" in error_msg.lower():
            return f"Error: 模型不存在"
        elif "429" in error_msg or "rate" in error_msg.lower():
            return f"Error: 请求频率过高"
        return f"Error: {error_msg[:300]}"


def is_llm_error(text: str) -> bool:
    return text.strip().startswith("Error:")


# ============================================
# LLMClient — 项目级角色配置解析 + 统一调用
# ============================================

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
        self.project_presets = project_presets or {}
        self.global_presets = global_presets or []

    def resolve_config(self, role: str) -> AgentConfig:
        """按角色解析最终 LLM 配置。

        优先级：project_presets[role] > project_presets["chat"] > global_presets[0] > 默认
        """
        preset = self._find_preset(role)
        if preset is None:
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

    # 角色名别名映射：数据库存 worker_preset，引擎查找 writer
    _ROLE_ALIASES = {
        "writer": "worker",
        "worker": "writer",
    }

    def _find_preset(self, role: str) -> Optional[Dict]:
        """按优先级查找 preset。

        优先级：project_presets[role] > project_presets[alias] > project_presets["chat"] > global_presets[0]
        """
        role_key = f"{role}_preset" if not role.endswith("_preset") else role
        alias = self._ROLE_ALIASES.get(role)
        alias_key = f"{alias}_preset" if alias and not alias.endswith("_preset") else alias

        # 1. 直接匹配
        p = self.project_presets.get(role) or self.project_presets.get(role_key)
        if p and isinstance(p, dict) and p.get("api_key"):
            return p

        # 2. 别名匹配（writer ↔ worker）
        if alias:
            p = self.project_presets.get(alias) or self.project_presets.get(alias_key)
            if p and isinstance(p, dict) and p.get("api_key"):
                return p

        # 3. chat 兜底
        p = self.project_presets.get("chat") or self.project_presets.get("chat_preset")
        if p and isinstance(p, dict) and p.get("api_key"):
            return p

        # 4. 全局预设
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
