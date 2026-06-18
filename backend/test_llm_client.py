"""LLM 客户端测试 — 覆盖 AgentConfig / is_llm_error / LLMClient / call_llm / LLMError 异常类层级。

LLM 调用全部 mock，不依赖真实 API。
"""
import sys
import os
import asyncio

sys.path.insert(0, '.')

from engines.common.llm_client import (
    AgentConfig, LLMClient, is_llm_error, call_llm,
    _is_retryable_error, _RETRYABLE_STATUS, _MAX_RETRIES,
    LLMError, LLMConfigError, LLMRateLimitError, LLMTimeoutError,
    LLMAuthError, LLMNotFoundError, LLMServerError, LLMEmptyResponseError,
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


# ============ 10. call_llm — 空 API Key 抛出 LLMConfigError ============
def t10():
    cfg = AgentConfig(api_key="", base_url="https://api.example.com", model="gpt-4")
    try:
        asyncio.run(call_llm(cfg, "sys", "usr", max_tokens=100, request_timeout_seconds=30))
        raise AssertionError("空 API Key 应抛出 LLMConfigError")
    except LLMConfigError as e:
        assert "API Key" in e.message, f"异常消息应包含 API Key，实际 {e.message!r}"
        assert e.retryable is False, "LLMConfigError 应不可重试"
        return f"抛出 LLMConfigError: {e}"


# ============ 11. call_llm — 空 base_url 抛出 LLMConfigError ============
def t11():
    cfg = AgentConfig(api_key="sk-test", base_url="", model="gpt-4")
    try:
        asyncio.run(call_llm(cfg, "sys", "usr", max_tokens=100, request_timeout_seconds=30))
        raise AssertionError("空 base_url 应抛出 LLMConfigError")
    except LLMConfigError as e:
        assert "Base URL" in e.message or "模型" in e.message, f"异常消息应说明配置缺失，实际 {e.message!r}"
        return f"抛出 LLMConfigError: {e}"


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


# ============ 15. call_llm — 模型返回空内容抛出 LLMEmptyResponseError ============
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
        try:
            asyncio.run(call_llm(cfg, "sys", "usr", max_tokens=100, request_timeout_seconds=30))
            raise AssertionError("空内容应抛出 LLMEmptyResponseError")
        except LLMEmptyResponseError as e:
            assert "为空" in e.message or "不支持" in e.message, f"异常消息应说明空响应，实际 {e.message!r}"
            assert e.retryable is False, "LLMEmptyResponseError 应不可重试"
            return f"抛出 LLMEmptyResponseError: {e}"
    finally:
        llm_mod.AsyncOpenAI = original


# ============ 16. call_llm — 401 错误抛出 LLMAuthError（不可重试） ============
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
        try:
            asyncio.run(call_llm(cfg, "sys", "usr", max_tokens=100, request_timeout_seconds=30))
            raise AssertionError("401 错误应抛出 LLMAuthError")
        except LLMAuthError as e:
            assert "API Key" in e.message or "认证失败" in e.message or "401" in e.message, f"异常消息应说明认证失败，实际 {e.message!r}"
            assert e.retryable is False, "LLMAuthError 应不可重试"
            return f"抛出 LLMAuthError: {e}"
    finally:
        llm_mod.AsyncOpenAI = original


# ============ 17. call_llm — 404 模型不存在抛出 LLMNotFoundError ============
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
        try:
            asyncio.run(call_llm(cfg, "sys", "usr", max_tokens=100, request_timeout_seconds=30))
            raise AssertionError("404 错误应抛出 LLMNotFoundError")
        except LLMNotFoundError as e:
            assert "模型不存在" in e.message or "not found" in e.message.lower() or "404" in e.message, f"异常消息应说明模型不存在，实际 {e.message!r}"
            assert e.retryable is False, "LLMNotFoundError 应不可重试"
            return f"抛出 LLMNotFoundError: {e}"
    finally:
        llm_mod.AsyncOpenAI = original


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


# ============ 21. LLMClient.call_strict — 未配置抛出 LLMConfigError ============
def t21():
    client = LLMClient(project_presets={}, global_presets=[])
    try:
        asyncio.run(client.call_strict("writer", "system", "user"))
        raise AssertionError("未配置应抛出 LLMConfigError")
    except LLMConfigError as e:
        assert "API Key" in e.message or "未配置" in e.message, f"异常消息应说明未配置，实际 {e.message!r}"
        return f"call_strict 抛出 LLMConfigError: {e}"


# ============ 22. LLMClient.call_strict — 成功路径返回文本 ============
def t22():
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
        assert config.api_key == "sk-test"
        assert system_prompt == "sys"
        assert user_prompt == "usr"
        return "strict 模式返回内容"

    original = llm_mod.call_llm
    llm_mod.call_llm = _mock_call_llm
    try:
        result = asyncio.run(client.call_strict("writer", "sys", "usr"))
    finally:
        llm_mod.call_llm = original
    assert result == "strict 模式返回内容", f"call_strict 应返回 LLM 文本，实际 {result!r}"
    return "call_strict 成功路径 OK"


# ============ 23. 异常类 retryable 属性 ============
def t23():
    # 可重试异常
    assert LLMRateLimitError("429").retryable is True, "LLMRateLimitError 应可重试"
    assert LLMTimeoutError("timeout").retryable is True, "LLMTimeoutError 应可重试"
    assert LLMServerError("500").retryable is True, "LLMServerError 应可重试"
    # 不可重试异常
    assert LLMConfigError("config").retryable is False, "LLMConfigError 应不可重试"
    assert LLMAuthError("401").retryable is False, "LLMAuthError 应不可重试"
    assert LLMNotFoundError("404").retryable is False, "LLMNotFoundError 应不可重试"
    assert LLMEmptyResponseError("empty").retryable is False, "LLMEmptyResponseError 应不可重试"
    # 基类默认不可重试，但可通过参数指定
    assert LLMError("base").retryable is False, "LLMError 基类默认应不可重试"
    assert LLMError("custom", retryable=True).retryable is True, "LLMError 基类应支持 retryable=True"
    return "retryable 属性 OK"


# ============ 24. LLMError.__str__ 返回 [LLM_ERROR: ...] 格式 ============
def t24():
    e = LLMConfigError("API Key 未配置")
    s = str(e)
    assert s.startswith("[LLM_ERROR: "), f"__str__ 应以 [LLM_ERROR: 开头，实际 {s!r}"
    assert s.endswith("]"), f"__str__ 应以 ] 结尾，实际 {s!r}"
    assert "API Key 未配置" in s, f"__str__ 应包含消息内容，实际 {s!r}"
    # 验证 is_llm_error 与 __str__ 的一致性
    assert is_llm_error(s) is True, f"is_llm_error 应识别 __str__ 输出，实际 {s!r}"
    # 各子类的 __str__ 都应遵循格式
    for cls, msg in [
        (LLMRateLimitError, "rate limit"),
        (LLMTimeoutError, "timeout"),
        (LLMAuthError, "auth"),
        (LLMNotFoundError, "not found"),
        (LLMServerError, "server error"),
        (LLMEmptyResponseError, "empty"),
    ]:
        s = str(cls(msg))
        assert s.startswith("[LLM_ERROR: ") and s.endswith("]"), f"{cls.__name__}.__str__ 格式错误: {s!r}"
        assert is_llm_error(s) is True, f"is_llm_error 应识别 {cls.__name__} 的 __str__ 输出"
    return "__str__ 格式一致性 OK"


if __name__ == '__main__':
    print("=" * 70)
    print("  LLM 客户端测试 (24 用例)")
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
    run("10. call_llm 空 API Key 抛 LLMConfigError", t10)
    run("11. call_llm 空 base_url 抛 LLMConfigError", t11)
    run("12. _is_retryable_error 判定", t12)
    run("13. 重试常量", t13)
    run("14. call_llm mock AsyncOpenAI 正常", t14)
    run("15. call_llm 空内容抛 LLMEmptyResponseError", t15)
    run("16. call_llm 401 抛 LLMAuthError", t16)
    run("17. call_llm 404 抛 LLMNotFoundError", t17)
    run("18. call 使用角色默认 max_tokens", t18)
    run("19. call LLM_ERROR 透传", t19)
    run("20. worker ↔ writer 别名映射", t20)
    run("21. call_strict 未配置抛 LLMConfigError", t21)
    run("22. call_strict 成功路径返回文本", t22)
    run("23. 异常类 retryable 属性", t23)
    run("24. LLMError.__str__ 格式一致性", t24)
    print()
    print("=" * 70)
    print(f"  结果:  {len(PASSED)} 通过 / {len(FAILED)} 失败")
    print("=" * 70)
    sys.exit(0 if not FAILED else 1)
