"""Core behavior tests for TitleMiddleware."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

from langchain_core.messages import AIMessage, HumanMessage

from src.agents.middlewares.title_middleware import TitleMiddleware
from src.config.title_config import TitleConfig, get_title_config, set_title_config


def _clone_title_config(config: TitleConfig) -> TitleConfig:
    # Avoid mutating shared global config objects across tests.
    return TitleConfig(**config.model_dump())


def _set_test_title_config(**overrides) -> TitleConfig:
    config = _clone_title_config(get_title_config())
    for key, value in overrides.items():
        setattr(config, key, value)
    set_title_config(config)
    return config


class TestTitleMiddlewareCoreLogic:
    def setup_method(self):
        # Title config is a global singleton; snapshot and restore for test isolation.
        self._original = _clone_title_config(get_title_config())

    def teardown_method(self):
        set_title_config(self._original)

    def test_should_generate_title_for_first_complete_exchange(self):
        _set_test_title_config(enabled=True)
        middleware = TitleMiddleware()
        state = {
            "messages": [
                HumanMessage(content="帮我总结这段代码"),
                AIMessage(content="好的，我先看结构"),
            ]
        }

        assert middleware._should_generate_title(state) is True

    def test_should_not_generate_title_when_disabled_or_already_set(self):
        middleware = TitleMiddleware()

        _set_test_title_config(enabled=False)
        disabled_state = {
            "messages": [HumanMessage(content="Q"), AIMessage(content="A")],
            "title": None,
        }
        assert middleware._should_generate_title(disabled_state) is False

        _set_test_title_config(enabled=True)
        titled_state = {
            "messages": [HumanMessage(content="Q"), AIMessage(content="A")],
            "title": "Existing Title",
        }
        assert middleware._should_generate_title(titled_state) is False

    def test_should_not_generate_title_after_second_user_turn(self):
        _set_test_title_config(enabled=True)
        middleware = TitleMiddleware()
        state = {
            "messages": [
                HumanMessage(content="第一问"),
                AIMessage(content="第一答"),
                HumanMessage(content="第二问"),
                AIMessage(content="第二答"),
            ]
        }

        assert middleware._should_generate_title(state) is False

    def test_generate_title_trims_quotes_and_respects_max_chars(self, monkeypatch):
        _set_test_title_config(max_chars=12)
        middleware = TitleMiddleware()
        fake_model = MagicMock()
        fake_model.ainvoke = AsyncMock(return_value=MagicMock(content='"A very long generated title"'))
        monkeypatch.setattr("src.agents.middlewares.title_middleware.create_chat_model", lambda **kwargs: fake_model)

        state = {
            "messages": [
                HumanMessage(content="请帮我写一个脚本"),
                AIMessage(content="好的，先确认需求"),
            ]
        }
        title = asyncio.run(middleware._generate_title(state))

        assert '"' not in title
        assert "'" not in title
        assert len(title) == 12

    def test_generate_title_handles_list_content(self, monkeypatch):
        """Model returning content as a list of blocks must not produce a raw repr string."""
        _set_test_title_config(max_chars=60)
        middleware = TitleMiddleware()
        fake_model = MagicMock()
        fake_model.ainvoke = AsyncMock(
            return_value=MagicMock(content=[{"type": "text", "text": "Extracted Title"}])
        )
        monkeypatch.setattr("src.agents.middlewares.title_middleware.create_chat_model", lambda **kwargs: fake_model)

        state = {
            "messages": [
                HumanMessage(content="请帮我写一个脚本"),
                AIMessage(content="好的，先确认需求"),
            ]
        }
        title = asyncio.run(middleware._generate_title(state))

        assert title == "Extracted Title"
        assert "[" not in title, "Raw list repr leaked into title"

    def test_generate_title_fallback_when_model_fails(self, monkeypatch):
        _set_test_title_config(max_chars=20)
        middleware = TitleMiddleware()
        fake_model = MagicMock()
        fake_model.ainvoke = AsyncMock(side_effect=RuntimeError("LLM unavailable"))
        monkeypatch.setattr("src.agents.middlewares.title_middleware.create_chat_model", lambda **kwargs: fake_model)

        state = {
            "messages": [
                HumanMessage(content="这是一个非常长的问题描述，需要被截断以形成fallback标题"),
                AIMessage(content="收到"),
            ]
        }
        title = asyncio.run(middleware._generate_title(state))

        # Assert behavior (truncated fallback + ellipsis) without overfitting exact text.
        assert title.endswith("...")
        assert title.startswith("这是一个非常长的问题描述")

    def test_aafter_model_returns_fallback_immediately_and_fires_background_task(self, monkeypatch):
        """aafter_model must return the fallback title without waiting for the LLM.

        The real title is generated asynchronously and patched into thread state
        via a background task; callers should not depend on the LLM-generated
        value being present in the returned dict.
        """
        from langchain_core.messages import AIMessage, HumanMessage

        middleware = TitleMiddleware()
        monkeypatch.setattr(middleware, "_should_generate_title", lambda state: True)

        # Simulate get_stream_writer and get_config so the async path doesn't crash.
        monkeypatch.setattr(
            "src.agents.middlewares.title_middleware.get_stream_writer",
            lambda: (lambda _evt: None),
        )
        monkeypatch.setattr(
            "src.agents.middlewares.title_middleware.get_config",
            lambda: {"configurable": {"thread_id": "test-thread"}},
        )

        state = {
            "messages": [
                HumanMessage(content="请帮我写一个脚本"),
                AIMessage(content="好的，先确认需求"),
            ]
        }
        result = asyncio.run(middleware.aafter_model(state, runtime=MagicMock()))

        # Must return a non-None dict with a non-empty title (the fallback).
        assert result is not None
        assert isinstance(result.get("title"), str)
        assert result["title"]

        monkeypatch.setattr(middleware, "_should_generate_title", lambda state: False)
        assert asyncio.run(middleware.aafter_model(state, runtime=MagicMock())) is None

    def test_after_agent_returns_generated_title_when_background_task_completed(self):
        """after_agent must return the LLM title once the background task has stored it.

        State now lives in run-scoped storage (keyed off the runtime object) so
        the singleton middleware instance doesn't leak titles across concurrent
        runs. The test pokes the storage directly.
        """
        from src.agents.middlewares.run_scoped import get_run_store
        from src.agents.middlewares.title_middleware import _TITLE_RESULT_KEY

        middleware = TitleMiddleware()
        runtime = MagicMock()
        get_run_store(runtime)[_TITLE_RESULT_KEY] = "LLM Generated Title"

        result = middleware.after_agent({}, runtime=runtime)
        assert result == {"title": "LLM Generated Title"}

    def test_after_agent_returns_none_when_background_task_not_yet_done(self):
        middleware = TitleMiddleware()
        # Fresh runtime → run-scoped store has no result key.
        assert middleware.after_agent({}, runtime=MagicMock()) is None

    def test_should_generate_title_with_synthetic_human_messages(self):
        """Synthetic HumanMessages (planner_handoff, todo_reminder, etc.) must not block title generation.

        Regression test for threads where the planner/todo middlewares inject
        named HumanMessage blocks before the title middleware runs.
        """
        _set_test_title_config(enabled=True)
        middleware = TitleMiddleware()
        state = {
            "messages": [
                HumanMessage(content="帮我总结这段代码"),
                AIMessage(content="好的，我先看结构"),
                HumanMessage(name="planner_handoff", content="<planner_handoff>...</planner_handoff>"),
                HumanMessage(name="todo_reminder", content="<todo_reminder>...</todo_reminder>"),
                AIMessage(content="这是分析结果"),
            ]
        }

        assert middleware._should_generate_title(state) is True

    def test_prepare_generation_picks_real_user_message_not_synthetic(self):
        """_prepare_generation must extract content from the real user message, not synthetic ones."""
        _set_test_title_config(enabled=True)
        middleware = TitleMiddleware()
        state = {
            "messages": [
                HumanMessage(name="planner_handoff", content="<planner_handoff>...</planner_handoff>"),
                HumanMessage(name="todo_reminder", content="<todo_reminder>...</todo_reminder>"),
                HumanMessage(content="帮我总结这段代码"),
                AIMessage(content="好的，我先看结构"),
            ]
        }

        prompt, user_msg, _, _ = middleware._prepare_generation(state)
        assert "帮我总结这段代码" in user_msg
        assert "planner_handoff" not in user_msg
        assert "todo_reminder" not in user_msg

    def test_prepare_generation_with_synthetic_before_real_user_message(self):
        """When synthetic messages appear before the real user message, content extraction still works."""
        _set_test_title_config(enabled=True)
        middleware = TitleMiddleware()
        state = {
            "messages": [
                HumanMessage(content="Initial user question"),
                AIMessage(content="First AI response"),
                HumanMessage(name="planner_handoff", content="<planner_handoff>...</planner_handoff>"),
                HumanMessage(name="todo_reminder", content="<todo_reminder>...</todo_reminder>"),
                AIMessage(content="Second AI response with analysis"),
            ]
        }

        prompt, user_msg, assistant_msg, _ = middleware._prepare_generation(state)
        assert "Initial user question" in user_msg
        assert "planner_handoff" not in user_msg
        assert "todo_reminder" not in user_msg

    def test_generate_title_returns_none_on_timeout(self, monkeypatch):
        """_generate_title returns None on TimeoutError and keeps the fallback title."""
        _set_test_title_config(max_chars=60)
        middleware = TitleMiddleware()
        fake_model = MagicMock()
        fake_model.ainvoke = AsyncMock(side_effect=TimeoutError())
        monkeypatch.setattr("src.agents.middlewares.title_middleware.create_chat_model", lambda **kwargs: fake_model)

        state = {
            "messages": [
                HumanMessage(content="请帮我写一个脚本"),
                AIMessage(content="好的"),
            ]
        }
        result = asyncio.run(middleware._generate_title(state))
        assert result is None, "TimeoutError should produce None, not a fallback string"

    def test_generate_title_returns_fallback_on_non_timeout_error(self, monkeypatch):
        """_generate_title must still return a fallback string for non-timeout errors."""
        _set_test_title_config(max_chars=60)
        middleware = TitleMiddleware()
        fake_model = MagicMock()
        fake_model.ainvoke = AsyncMock(side_effect=RuntimeError("service unavailable"))
        monkeypatch.setattr("src.agents.middlewares.title_middleware.create_chat_model", lambda **kwargs: fake_model)

        state = {
            "messages": [
                HumanMessage(content="请帮我写一个脚本"),
                AIMessage(content="好的"),
            ]
        }
        result = asyncio.run(middleware._generate_title(state))
        assert isinstance(result, str) and result, "Non-timeout errors should still yield a fallback string"

    def test_bg_task_does_not_retry_on_timeout(self, monkeypatch):
        """_bg() must not retry _generate_title when the first call times out."""
        _set_test_title_config(max_chars=60)
        middleware = TitleMiddleware()
        monkeypatch.setattr(middleware, "_should_generate_title", lambda s: True)

        call_count = 0

        async def _fake_generate(state):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return None  # simulate timeout
            return "Real Generated Title"

        monkeypatch.setattr(middleware, "_generate_title", _fake_generate)
        monkeypatch.setattr(
            "src.agents.middlewares.title_middleware.get_stream_writer",
            lambda: (lambda _: None),
        )
        monkeypatch.setattr(
            "src.agents.middlewares.title_middleware.get_config",
            lambda: {"configurable": {"thread_id": "t1"}},
        )
        monkeypatch.setattr(
            "src.agents.middlewares.title_middleware.append_runtime_event",
            lambda *a, **kw: None,
        )

        from src.agents.middlewares.run_scoped import get_run_store
        from src.agents.middlewares.title_middleware import _TITLE_RESULT_KEY

        state = {
            "messages": [
                HumanMessage(content="test"),
                AIMessage(content="answer"),
            ]
        }
        runtime = MagicMock()
        asyncio.run(middleware.aafter_model(state, runtime=runtime))

        assert call_count == 1, "_generate_title should not retry after timeout"
        # Title state lives in the run-scoped store keyed off `runtime`.
        assert get_run_store(runtime).get(_TITLE_RESULT_KEY) is None

    def test_aafter_agent_does_not_wait_when_title_await_timeout_is_zero(self):
        from src.agents.middlewares.run_scoped import get_run_store
        from src.agents.middlewares.title_middleware import _TITLE_BG_TASK_KEY

        _set_test_title_config(await_generated_title_timeout_seconds=0)
        middleware = TitleMiddleware()

        async def _slow_task():
            await asyncio.sleep(10)

        async def _run():
            runtime = MagicMock()
            store = get_run_store(runtime)
            store[_TITLE_BG_TASK_KEY] = asyncio.create_task(_slow_task())
            result = await middleware.aafter_agent({}, runtime=runtime)
            assert result is None
            assert store.get(_TITLE_BG_TASK_KEY) is None

        asyncio.run(_run())
