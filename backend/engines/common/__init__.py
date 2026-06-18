"""写作引擎公共层 — 三引擎共享的 MWR 循环骨架、LLM 客户端、KG 适配器、状态管理、体裁适配器、反幻觉。"""

from .base_engine import BaseEngine, MWRTask, Draft, ReviewResult, FinalDecision
from .llm_client import (
    LLMClient, AgentConfig, call_llm, is_llm_error,
    LLMError, LLMConfigError, LLMRateLimitError, LLMTimeoutError,
    LLMAuthError, LLMNotFoundError, LLMServerError, LLMEmptyResponseError,
)
from .kg_adapter import KGAdapter
from .state import EngineState
from .genre_adapter import GenreAdapter
from .hallucination_guard import HallucinationGuardAdapter
from .prompts import (
    MANAGER_SYSTEM, WRITER_SYSTEM_OUTLINE, WRITER_SYSTEM_WRITING, WRITER_SYSTEM_POLISH,
    REVIEWER_SYSTEM_OUTLINE, REVIEWER_SYSTEM_WRITING, REVIEWER_SYSTEM_REVIEW,
    CHAT_SYSTEM, HALLUCINATION_CHECK_PROMPT, OUTPUT_FORMAT_CONSTRAINT,
    KG_INGEST_SYSTEM, KG_INGEST_OUTLINE_SYSTEM,
)

__all__ = [
    "BaseEngine", "MWRTask", "Draft", "ReviewResult", "FinalDecision",
    "LLMClient", "AgentConfig", "call_llm", "is_llm_error",
    "LLMError", "LLMConfigError", "LLMRateLimitError", "LLMTimeoutError",
    "LLMAuthError", "LLMNotFoundError", "LLMServerError", "LLMEmptyResponseError",
    "KGAdapter", "EngineState",
    "GenreAdapter", "HallucinationGuardAdapter",
    "MANAGER_SYSTEM", "WRITER_SYSTEM_OUTLINE", "WRITER_SYSTEM_WRITING", "WRITER_SYSTEM_POLISH",
    "REVIEWER_SYSTEM_OUTLINE", "REVIEWER_SYSTEM_WRITING", "REVIEWER_SYSTEM_REVIEW",
    "CHAT_SYSTEM", "HALLUCINATION_CHECK_PROMPT", "OUTPUT_FORMAT_CONSTRAINT",
    "KG_INGEST_SYSTEM", "KG_INGEST_OUTLINE_SYSTEM",
]
