"""Tests for CapybaraSummarizationMiddleware — skill rescue and hook dispatch."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from src.agents.middlewares.summarization_middleware import (
    BeforeSummarizationHook,
    CapybaraSummarizationMiddleware,
    SummarizationEvent,
)


def _runtime(thread_id: str = "t1", agent_name: str | None = None):
    ctx: dict = {"thread_id": thread_id}
    if agent_name:
        ctx["agent_name"] = agent_name
    return SimpleNamespace(context=ctx)


def _human(content: str = "hi", name: str | None = None) -> HumanMessage:
    msg = HumanMessage(content=content)
    if name:
        msg.name = name
    return msg


def _skill_msg(content: str = "skill body") -> HumanMessage:
    return _human(content=content, name="active_skills")


def _ai_tool(path: str) -> tuple[AIMessage, ToolMessage]:
    """Return an (AIMessage with read_file tool call, paired ToolMessage)."""
    tc_id = f"tc-{path}"
    ai = AIMessage(content="")
    ai.tool_calls = [{"name": "read_file", "args": {"path": path}, "id": tc_id}]
    tm = ToolMessage(content=f"contents of {path}", tool_call_id=tc_id)
    return ai, tm


def _make_mw(*, hooks=None, skill_count=3, skill_tokens=10_000) -> CapybaraSummarizationMiddleware:
    model_mock = MagicMock()
    model_mock._llm_type = "mock"
    model_mock.profile = None
    model_mock.invoke.return_value = MagicMock(text="[summary]")
    with patch("langchain.agents.middleware.summarization.init_chat_model", return_value=model_mock):
        mw = CapybaraSummarizationMiddleware(
            model="mock-model",
            trigger=("messages", 1),  # trigger immediately for testing
            keep=("messages", 1),
            before_summarization=hooks or [],
            preserve_recent_skill_count=skill_count,
            preserve_recent_skill_tokens=skill_tokens,
        )
    mw.model = model_mock
    mw.token_counter = lambda msgs: len(msgs) * 10
    return mw


# ---------------------------------------------------------------------------
# Skill rescue — active_skills HumanMessages are preserved
# ---------------------------------------------------------------------------


class TestSkillRescue:
    def test_skill_messages_rescued_from_summarization(self):
        mw = _make_mw()
        old_skill = _skill_msg("old skill body")
        recent_skill = _skill_msg("recent skill body")

        # Partition: [old_skill, recent_skill] to summarize.
        to_summarize = [old_skill, recent_skill]
        rescued, remaining = mw._rescue_skill_messages(to_summarize)

        # Both skills should be rescued (within budget)
        assert old_skill in rescued or recent_skill in rescued
        # Rescued skills should not appear in remaining
        for msg in rescued:
            assert msg not in remaining

    def test_skill_rescue_respects_count_limit(self):
        mw = _make_mw(skill_count=1)
        skills = [_skill_msg(f"skill {i}") for i in range(5)]
        rescued, remaining = mw._rescue_skill_messages(skills)
        assert len(rescued) == 1

    def test_skill_rescue_respects_token_budget(self):
        # token_counter returns len(msgs)*10, so each skill = 10 tokens
        # budget = 15 → only 1 skill fits
        mw = _make_mw(skill_tokens=15)
        skills = [_skill_msg(f"skill {i}") for i in range(4)]
        rescued, _ = mw._rescue_skill_messages(skills)
        assert len(rescued) == 1

    def test_no_skill_messages_returns_empty(self):
        mw = _make_mw()
        msgs = [_human("a"), _human("b"), AIMessage(content="c")]
        rescued, remaining = mw._rescue_skill_messages(msgs)
        assert rescued == []
        assert len(remaining) == len(msgs)

    def test_rescued_skills_prepended_to_preserved(self):
        mw = _make_mw()
        skill = _skill_msg("body")
        plain = _human("user")
        to_summarize = [plain, skill]
        rescued, remaining = mw._rescue_skill_messages(to_summarize)
        assert skill in rescued
        assert skill not in remaining

    def test_partition_with_skill_rescue_integrates(self):
        mw = _make_mw()
        msgs = [
            _human("old user"),
            _skill_msg("skill body"),
            _human("new user"),
            AIMessage(content="ai response"),
        ]
        # Ensure all have IDs
        for i, m in enumerate(msgs):
            m.id = f"msg-{i}"

        # cutoff at 2: first two go to summarize, last two preserved
        to_summarize, preserved = mw._partition_with_skill_rescue(msgs, cutoff_index=2)

        # The skill message that was going to be summarized should be rescued
        skill_in_preserved = any(
            getattr(m, "name", None) == "active_skills" for m in preserved
        )
        assert skill_in_preserved


# ---------------------------------------------------------------------------
# Hook dispatch
# ---------------------------------------------------------------------------


class TestHookDispatch:
    def test_hook_called_before_summarization(self):
        fired_events = []

        def hook(event: SummarizationEvent) -> None:
            fired_events.append(event)

        mw = _make_mw(hooks=[hook])
        to_summarize = [_human("old")]
        preserved = [_human("new")]
        rt = _runtime(thread_id="t-hook", agent_name="agent-1")

        mw._fire_hooks(to_summarize, preserved, rt)

        assert len(fired_events) == 1
        event = fired_events[0]
        assert event.thread_id == "t-hook"
        assert event.agent_name == "agent-1"
        assert len(event.messages_to_summarize) == 1
        assert len(event.preserved_messages) == 1

    def test_hook_failure_does_not_propagate(self):
        def bad_hook(event: SummarizationEvent) -> None:
            raise RuntimeError("hook error")

        mw = _make_mw(hooks=[bad_hook])
        # Should not raise
        mw._fire_hooks([_human("a")], [_human("b")], _runtime())

    def test_multiple_hooks_all_called(self):
        called = []
        mw = _make_mw(hooks=[lambda e: called.append("h1"), lambda e: called.append("h2")])
        mw._fire_hooks([_human("a")], [], _runtime())
        assert called == ["h1", "h2"]

    def test_no_hooks_no_error(self):
        mw = _make_mw(hooks=[])
        mw._fire_hooks([], [], _runtime())  # should not raise


# ---------------------------------------------------------------------------
# SummarizationEvent dataclass
# ---------------------------------------------------------------------------


def test_summarization_event_immutable():
    rt = _runtime()
    event = SummarizationEvent(
        messages_to_summarize=(_human("a"),),
        preserved_messages=(),
        thread_id="t1",
        agent_name=None,
        runtime=rt,
    )
    with pytest.raises((TypeError, AttributeError)):
        event.thread_id = "t2"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# BeforeSummarizationHook protocol
# ---------------------------------------------------------------------------


def test_hook_protocol_satisfied():
    def my_hook(event: SummarizationEvent) -> None:
        pass

    assert isinstance(my_hook, BeforeSummarizationHook)


def test_force_compaction_compacts_even_when_threshold_not_met():
    mw = _make_mw()
    mw._should_summarize = lambda messages, total_tokens: False  # type: ignore[method-assign]
    messages = [_human("first"), AIMessage(content="second"), _human("third")]
    for i, msg in enumerate(messages):
        msg.id = f"msg-{i}"
    state = {"messages": messages, "force_compaction_once": True}

    result = mw.before_model(state, _runtime())
    assert result is not None
    assert "messages" in result


def test_default_behavior_still_skips_when_threshold_not_met():
    mw = _make_mw()
    mw._should_summarize = lambda messages, total_tokens: False  # type: ignore[method-assign]
    messages = [_human("first"), AIMessage(content="second"), _human("third")]
    for i, msg in enumerate(messages):
        msg.id = f"msg-{i}"
    state = {"messages": messages}

    result = mw.before_model(state, _runtime())
    assert result is None
