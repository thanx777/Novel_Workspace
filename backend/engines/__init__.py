"""engines 包 — 写作引擎三阶段架构。

统一设置 sys.path，使子模块能导入 backend 根目录下的模块（outline_templates、genre_data 等）。
替代各子模块中分散的 sys.path.insert 黑魔法。
"""
import os as _os
import sys as _sys

# 将 backend 根目录加入 sys.path（仅一次）
_BACKEND_ROOT = _os.path.abspath(_os.path.join(_os.path.dirname(__file__), ".."))
if _BACKEND_ROOT not in _sys.path:
    _sys.path.insert(0, _BACKEND_ROOT)

from .common import BaseEngine, LLMClient, KGAdapter, EngineState
