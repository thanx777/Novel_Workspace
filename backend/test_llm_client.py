"""LLM 客户端测试 — 覆盖 AgentConfig / is_llm_error / LLMClient / call_llm。

LLM 调用全部 mock，不依赖真实 API。
"""
import sys
import os
import asyncio

sys.path.insert(0, '.')

from engines.common.llm_client import (
    AgentConfig, LLMClient, is_llm_error, call_llm,
    _is_retryable_error, _RETRYABLE_STATUS, _MAX_RETRIES,
)

PASSED, FAILED = [], []


def run(name, fn):
    try:
        r = fn()
        PASSED.append((name, r))
        print(f"  ✅ {name}")
    except Exception as e:
        FAILED.append((name, str(e)))
        print(f"  ❌ {name} → {e}")


# ============ 1. is_llm_error 检测前缀 ============
def t01():
    assert is_llm_error("[LLM_ERROR: API Key 未配置]") is True
    assert is_llm_error("  [LLM_ERROR: xxx]") is True  # 带前导空格也应识别
    assert is_llm_error("正常文本内容") is False
    assert is_llm_error("[LLM_ERROR") is True  # 不需要右括号
    assert is_llm_error("") is False
    return "OK"


# ============ 2. AgentConfig 数据类默认值 ============
def t02():
    cfg = AgentConfig(api_key="sk-test")
    assert cfg.api_key == "sk-test"
    assert cfg.base_url == "https://open.bigmodel.cn/api/paas/v4"
    assert cfg.model == "glm-4-flash"
    assert cfg.api_format == "openai"
    assert cfg.chat_template_kwargs is None
    assert cfg.thinking_mode is None
    return "默认值 OK"


# ============ 3. AgentConfig 自定义字段 ============
def t03():
    cfg = AgentConfig(
        api_key="sk-xxx",
        base_url="https://api.deepseek.com/v1",
        model="deepseek-chat",
        api_format="openai",
        thinking_mode="enabled",
    )
    assert cfg.api_key == "sk-xxx"
    assert cfg.base_url == "https://api.deepseek.com/v1"
    assert cfg.model == "deepseek-chat"
    assert cfg.thinking_mode == "enabled"
    return "自定义字段 OK"


# ============ 4. LLMClient.has_valid_config — 未配置返回 False ============
def t04():
    client = LLMClient(project_presets={}, global_presets=[])
    assert client.has_valid_config("writer") is False
    assert client.has_valid_config("manager") is False
    assert client.has_valid_config("reviewer") is False
    return "未配置时返回 False OK"


# ============ 5. LLMClient.has_valid_config — 已配置返回 True ============
def t05():
    presets = {
        "writer_preset": {
            "api_key": "sk-test",
            "base_url": "https://api.example.com",
            "model": "gpt-4",
        }
    }
    client = LLMClient(project_presets=presets, global_presets=[])
    assert client.has_valid_config("writer") is True
    # worker 别名应等价于 writer
    assert client.has_valid_config("worker") is True
    return "已配置返回 True OK"


# ============ 6. LLMClient.resolve_config — 优先级：project > global ============
def t06():
    project_presets = {
        "writer_preset": {
            "api_key": "sk-proj",
            "base_url": "https://proj.example.com",
            "model": "proj-model",
        }
    }
    global_presets = [
        {"api_key": "sk-global", "base_url": "https://global.example.com", "model": "global-model"}
    ]
    client = LLMClient(project_presets=project_presets, global_presets=global_presets)
    cfg = client.resolve_config("writer")
    assert cfg.api_key == "sk-proj", f"应优先 project_presets，实际 {cfg.api_key}"
    assert cfg.model == "proj-model"
    return "优先级 OK"


# ============ 7. LLMClient.resolve_config — chat 兜底 ============
def t07():
    project_presets = {
        "chat_preset": {
            "api_key": "sk-chat",
            "base_url": "https://chat.example.com",
            "model": "chat-model",
        }
    }
    client = LLMClient(project_presets=project_presets, global_presets=[])
    # 没有专门的 reviewer 配置，应回退到 chat
    cfg = client.resolve_config("reviewer")
    assert cfg.api_key == "sk-chat", f"应回退到 chat，实际 {cfg.api_key}"
    return "chat 兜底 OK"


# ============ 8. LLMClient.call — 未配置返回 LLM_ERROR ============
def t08():
    client = LLMClient(project_presets={}, global_presets=[])
    result = asyncio.run(client.call("writer", "system", "user"))
    assert is_llm_error(result), f"未配置应返回 LLM_ERROR，实际 {result!r}"
    assert "API Key" in result or "未配置" in result
    return f"返回 {result[:50]}"


# ============ 9. LLMClient.call — mock call_llm 返回正常内容 ============
def t09():
    presets = {
        "writer_preset": {
            "api_key": "sk-test",
            "base_url": "https://api.example.com",
            "model": "gpt-4",
        }
    }
    client = LLMClient(project_presets=presets, global_presets=[])

    # mock call_llm 函数
    import engines.common.llm_client as llm_mod

    original = llm_mod.call_llm

    async def _mock_call_llm(config, system_prompt, user_prompt, max_tokens, request_timeout_seconds):
        # 验证传入的 config
        assert config.api_key == "sk-test"
        assert system_prompt == "sys"
        assert user_prompt == "usr"
        return "这是 LLM 返回的内容"

    llm_mod.call_llm = _mock_call_llm
    try:
        result = asyncio.run(client.call("writer", "sys", "usr"))
    finally:
        llm_mod.call_llm = original
    assert result == "这是 LLM 返回的内容"
    return "mock call_llm OK"


# ============ 10. call_llm — 空 API Key 返回 LLM_ERROR ============
def t10():
    cfg = AgentConfig(api_key="", base_url="https://api.example.com", model="gpt-4")
    result = asyncio.run(call_llm(cfg, "sys", "usr", max_tokens=100, request_timeout_seconds=30))
    assert is_llm_error(result)
    assert "API Key" in result
    return "空 API Key OK"


# ============ 11. call_llm — 空 base_url 返回 LLM_ERROR ============
def t11():
    cfg = AgentConfig(api_key="sk-test", base_url="", model="gpt-4")
    result = asyncio.run(call_llm(cfg, "sys", "usr", max_tokens=100, request_timeout_seconds=30))
    assert is_llm_error(result)
    return "空 base_url OK"


# ============ 12. _is_retryable_error 判定 ============
def t12():
    assert _is_retryable_error("Connection timed out") is True
    assert _is_retryable_error("timeout occurred") is True
    assert _is_retryable_error("HTTP 429 Too Many Requests") is True
    assert _is_retryable_error("rate limit exceeded") is True
    assert _is_retryable_error("HTTP 500 Internal Server Error") is True
    assert _is_retryable_error("connection reset by peer") is True
    assert _is_retryable_error("service temporarily unavailable") is True
    # 不可重试的错误
    assert _is_retryable_error("HTTP 401 Unauthorized") is False
    assert _is_retryable_error("invalid api key") is False
    assert _is_retryable_error("model not found") is False
    return "重试判定 OK"


# ============ 13. _RETRYABLE_STATUS 与 _MAX_RETRIES 常量 ============
def t13():
    assert 429 in _RETRYABLE_STATUS
    assert 500 in _RETRYABLE_STATUS
    assert 502 in _RETRYABLE_STATUS
    assert 503 in _RETRYABLE_STATUS
    assert 504 in _RETRYABLE_STATUS
    # 4xx 客户端错误不应可重试
    assert 400 not in _RETRYABLE_STATUS
    assert 401 not in _RETRYABLE_STATUS
    assert 404 not in _RETRYABLE_STATUS
    assert _MAX_RETRIES == 3
    return "常量 OK"


# ============ 14. call_llm — mock openai 客户端返回内容 ============
def t14():
    """mock AsyncOpenAI.chat.completions.create，验证请求构造和响应解析。"""
    cfg = AgentConfig(
        api_key="sk-test",
        base_url="https://api.example.com/v1",
        model="gpt-4",
        api_format="openai",
    )

    # 用 monkeypatch 替换 AsyncOpenAI
    import engines.common.llm_client as llm_mod

    class _MockMessage:
        def __init__(self, content):
            self.content = content
            self.reasoning_content = None

    class _MockChoice:
        def __init__(self, content):
            self.message = _MockMessage(content)

    class _MockResponse:
        def __init__(self, content):
            self.choices = [_MockChoice(content)]

    class _MockCompletions:
        async def create(self, **kwargs):
            # 验证请求构造
            assert kwargs["model"] == "gpt-4"
            assert kwargs["messages"][0]["role"] == "system"
            assert kwargs["messages"][0]["content"] == "sys"
            assert kwargs["messages"][1]["role"] == "user"
            assert kwargs["messages"][1]["content"] == "usr"
            assert kwargs["max_tokens"] == 100
            assert kwargs["stream"] is False
            return _MockResponse("mocked LLM response")

    class _MockAsyncOpenAI:
        def __init__(self, **kwargs):
            self.chat = type("_Chat", (), {"completions": _MockCompletions()})()

    original = llm_mod.AsyncOpenAI
    llm_mod.AsyncOpenAI = _MockAsyncOpenAI
    try:
        result = asyncio.run(call_llm(cfg, "sys", "usr", max_tokens=100, request_timeout_seconds=30))
    finally:
        llm_mod.AsyncOpenAI = original
    assert result == "mocked LLM response"
    return "mock AsyncOpenAI OK"


# ============ 15. call_llm — 模型返回空内容 ============
def t15():
    cfg = AgentConfig(
        api_key="sk-test",
        base_url="https://api.example.com/v1",
        model="gpt-4",
    )
    import engines.common.llm_client as llm_mod

    class _MockMessage:
        def __init__(self):
            self.content = ""
            self.reasoning_content = None

    class _MockChoice:
        def __init__(self):
            self.message = _MockMessage()

    class _MockResponse:
        def __init__(self):
            self.choices = [_MockChoice()]

    class _MockCompletions:
        async def create(self, **kwargs):
            return _MockResponse()

    class _MockAsyncOpenAI:
        def __init__(self, **kwargs):
            self.chat = type("_Chat", (), {"completions": _MockCompletions()})()

    original = llm_mod.AsyncOpenAI
    llm_mod.AsyncOpenAI = _MockAsyncOpenAI
    try:
        result = asyncio.run(call_llm(cfg, "sys", "usr", max_tokens=100, request_timeout_seconds=30))
    finally:
        llm_mod.AsyncOpenAI = original
    assert is_llm_error(result), f"空内容应返回 LLM_ERROR，实际 {result!r}"
    assert "为空" in result or "不支持" in result
    return "空内容 OK"


# ============ 16. call_llm — 401 错误（不可重试，立即返回） ============
def t16():
    cfg = AgentConfig(
        api_key="sk-invalid",
        base_url="https://api.example.com/v1",
        model="gpt-4",
    )
    import engines.common.llm_client as llm_mod

    class _MockCompletions:
        async def create(self, **kwargs):
            raise Exception("401 Unauthorized: invalid api key")

    class _MockAsyncOpenAI:
        def __init__(self, **kwargs):
            self.chat = type("_Chat", (), {"completions": _MockCompletions()})()

    original = llm_mod.AsyncOpenAI
    llm_mod.AsyncOpenAI = _MockAsyncOpenAI
    try:
        result = asyncio.run(call_llm(cfg, "sys", "usr", max_tokens=100, request_timeout_seconds=30))
    finally:
        llm_mod.AsyncOpenAI = original
    assert is_llm_error(result)
    assert "401" in result or "API Key" in result or "认证失败" in result
    return "401 错误 OK"


# ============ 17. call_llm — 404 模型不存在 ============
def t17():
    cfg = AgentConfig(
        api_key="sk-test",
        base_url="https://api.example.com/v1",
        model="nonexistent-model",
    )
    import engines.common.llm_client as llm_mod

    class _MockCompletions:
        async def create(self, **kwargs):
            raise Exception("404 Not Found: model does not exist")

    class _MockAsyncOpenAI:
        def __init__(self, **kwargs):
            self.chat = type("_Chat", (), {"completions": _MockCompletions()})()

    original = llm_mod.AsyncOpenAI
    llm_mod.AsyncOpenAI = _MockAsyncOpenAI
    try:
        result = asyncio.run(call_llm(cfg, "sys", "usr", max_tokens=100, request_timeout_seconds=30))
    finally:
        llm_mod.AsyncOpenAI = original
    assert is_llm_error(result)
    assert "404" in result or "模型不存在" in result or "not found" in result.lower()
    return "404 错误 OK"


# ============ 18. LLMClient.call — max_tokens 使用角色默认值 ============
def t18():
    presets = {
        "reviewer_preset": {
            "api_key": "sk-test",
            "base_url": "https://api.example.com",
            "model": "gpt-4",
        }
    }
    client = LLMClient(project_presets=presets, global_presets=[])

    import engines.common.llm_client as llm_mod

    captured = {}

    async def _mock_call_llm(config, system_prompt, user_prompt, max_tokens, request_timeout_seconds):
        captured["max_tokens"] = max_tokens
        return "ok"

    llm_mod.call_llm = _mock_call_llm
    try:
        asyncio.run(client.call("reviewer", "sys", "usr"))
    finally:
        if hasattr(llm_mod, "_original_call_llm"):
            llm_mod.call_llm = llm_mod._original_call_llm
    # reviewer 默认 max_tokens=2000
    assert captured.get("max_tokens") == 2000, f"reviewer 默认 max_tokens 应为 2000，实际 {captured.get('max_tokens')}"
    return "max_tokens 默认值 OK"


# ============ 19. LLMClient.call — LLM_ERROR 透传 ============
def t19():
    presets = {
        "writer_preset": {
            "api_key": "sk-test",
            "base_url": "https://api.example.com",
            "model": "gpt-4",
        }
    }
    client = LLMClient(project_presets=presets, global_presets=[])

    import engines.common.llm_client as llm_mod

    async def _mock_call_llm(config, system_prompt, user_prompt, max_tokens, request_timeout_seconds):
        return "[LLM_ERROR: 请求超时]"

    llm_mod.call_llm = _mock_call_llm
    try:
        result = asyncio.run(client.call("writer", "sys", "usr"))
    finally:
        if hasattr(llm_mod, "_original_call_llm"):
            llm_mod.call_llm = llm_mod._original_call_llm
    assert is_llm_error(result)
    return "LLM_ERROR 透传 OK"


# ============ 20. LLMClient 别名映射 worker ↔ writer ============
def t20():
    presets = {
        "worker_preset": {
            "api_key": "sk-worker",
            "base_url": "https://api.example.com",
            "model": "worker-model",
        }
    }
    client = LLMClient(project_presets=presets, global_presets=[])
    # writer 应能通过 worker 别名找到配置
    cfg = client.resolve_config("writer")
    assert cfg.api_key == "sk-worker", f"writer 应通过 worker 别名解析，实际 {cfg.api_key}"
    assert cfg.model == "worker-model"
    assert client.has_valid_config("writer") is True
    return "worker ↔ writer 别名 OK"


if __name__ == '__main__':
    print("=" * 70)
    print("  LLM 客户端测试 (20 用例)")
    print("=" * 70)
    print()
    run("01. is_llm_error 检测前缀", t01)
    run("02. AgentConfig 默认值", t02)
    run("03. AgentConfig 自定义字段", t03)
    run("04. has_valid_config 未配置返回 False", t04)
    run("05. has_valid_config 已配置返回 True", t05)
    run("06. resolve_config 优先级", t06)
    run("07. resolve_config chat 兜底", t07)
    run("08. call 未配置返回 LLM_ERROR", t08)
    run("09. call mock call_llm 正常返回", t09)
    run("10. call_llm 空 API Key", t10)
    run("11. call_llm 空 base_url", t11)
    run("12. _is_retryable_error 判定", t12)
    run("13. 重试常量", t13)
    run("14. call_llm mock AsyncOpenAI 正常", t14)
    run("15. call_llm 模型返回空内容", t15)
    run("16. call_llm 401 错误", t16)
    run("17. call_llm 404 错误", t17)
    run("18. call 使用角色默认 max_tokens", t18)
    run("19. call LLM_ERROR 透传", t19)
    run("20. worker ↔ writer 别名映射", t20)
    print()
    print("=" * 70)
    print(f"  结果:  {len(PASSED)} 通过 / {len(FAILED)} 失败")
    print("=" * 70)
    sys.exit(0 if not FAILED else 1)
