"""Tests for CapyHomeSummarizationMiddleware — skill rescue and hook dispatch."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from src.agents.memory.summarization_hook import memory_flush_hook
from src.agents.middlewares.summarization_middleware import (
    DEFAULT_SUMMARY_PROMPT,
    BeforeSummarizationHook,
    CapyHomeSummarizationMiddleware,
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


def _make_mw(
    *,
    hooks=None,
    skill_count=3,
    skill_tokens=10_000,
    trigger=("messages", 1),
    keep=("messages", 1),
) -> CapyHomeSummarizationMiddleware:
    model_mock = MagicMock()
    model_mock._llm_type = "mock"
    model_mock.profile = None
    model_mock.invoke.return_value = MagicMock(text="[summary]")
    with patch("langchain.agents.middleware.summarization.init_chat_model", return_value=model_mock):
        mw = CapyHomeSummarizationMiddleware(
            model="mock-model",
            trigger=trigger,
            keep=keep,
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

    def test_operational_messages_rescued_from_summarization(self):
        mw = _make_mw()
        planner = _human("Original request: compare options", name="planner_handoff")
        old = _human("old context")
        latest = AIMessage(content="latest")
        msgs = [old, planner, latest]
        for i, msg in enumerate(msgs):
            msg.id = f"msg-{i}"

        to_summarize, preserved = mw._partition_with_skill_rescue(msgs, cutoff_index=2)

        assert planner in preserved
        assert planner not in to_summarize


# ---------------------------------------------------------------------------
# Tool-call ↔ tool-result pair rescue (#29)
# ---------------------------------------------------------------------------


class TestToolCallPairRescue:
    """Anthropic rejects context where a tool_use block has no matching
    tool_result block. The pair-rescue step must drag matching counterparts
    across the compaction boundary so the rebuilt thread stays valid."""

    def test_orphan_tool_result_drags_parent_ai_message_into_preserved(self):
        """ToolMessage stays in preserved but its parent AIMessage was being
        summarized — pair rescue must drag the AIMessage back."""
        mw = _make_mw()
        ai_with_tc, tool_result = _ai_tool("/tmp/a.txt")
        new_user = _human("follow-up question")
        msgs = [ai_with_tc, tool_result, new_user]
        for i, m in enumerate(msgs):
            m.id = f"m-{i}"

        # Cutoff at 1: AIMessage with tool_calls goes to_summarize,
        # ToolMessage + new_user are preserved. ToolMessage is now an
        # orphan tool_result — its parent tool_use is gone.
        to_summarize, preserved = mw._partition_with_skill_rescue(msgs, cutoff_index=1)

        assert ai_with_tc in preserved, "parent AIMessage must be rescued so tool_result is matched"
        assert tool_result in preserved
        assert ai_with_tc not in to_summarize

    def test_orphan_tool_use_case_is_not_auto_rescued(self, caplog):
        """The mirror case (AI with tool_calls in preserved, ToolMessage in
        remaining) cannot arise from normal partition flow — TMs always
        follow their parent AI in the original sequence, so if AI is
        at/after cutoff, TM is too. Auto-rescuing the TM by prepending
        would produce [TM, ..., AI] which violates Anthropic's invariant.

        We deliberately do NOT rescue in this direction; the coherence
        assertion logs a WARNING so any upstream bug producing this state
        is surfaced rather than silently masked with wrong ordering.
        """
        mw = _make_mw()
        caplog.set_level("WARNING")
        ai_with_tc, tool_result = _ai_tool("/tmp/b.txt")
        old_human = _human("earlier turn")
        new_user = _human("new turn")

        remaining = [old_human, tool_result]
        preserved = [ai_with_tc, new_user]

        new_remaining, rescued_preserved = mw._rescue_tool_call_pairs(remaining, preserved)

        # Asymmetric: the orphan_tool_use direction is a no-op rescue.
        assert rescued_preserved == [], (
            "auto-rescuing this direction would produce [TM, AI] — wrong order for Anthropic"
        )
        assert new_remaining == remaining

        # Coherence assertion should warn so the impossible-but-defensive case is loud.
        mw._assert_tool_pair_coherence(preserved)
        assert "orphan tool_call pairs" in caplog.text

    def test_pair_rescue_noop_when_already_coherent(self):
        """No mismatches → return ([], remaining/preserved unchanged sentinel)."""
        mw = _make_mw()
        ai_with_tc, tool_result = _ai_tool("/tmp/c.txt")
        old_human = _human("a")
        remaining = [old_human]
        preserved = [ai_with_tc, tool_result]

        new_remaining, rescued_preserved = mw._rescue_tool_call_pairs(remaining, preserved)

        # Sentinel: empty rescued_preserved signals "no change needed".
        assert rescued_preserved == []
        assert new_remaining == remaining

    def test_multi_tool_call_ai_rescued_when_both_tool_messages_orphan(self):
        """Realistic scenario: AIMessage(tool_calls=[X, Y]) is in remaining (to
        summarize), both TM(X) and TM(Y) are in preserved. The single AI must
        be rescued — one rescue covers both orphan tool_results."""
        mw = _make_mw()
        ai = AIMessage(content="")
        ai.tool_calls = [
            {"name": "read_file", "args": {"path": "/x"}, "id": "tc-x"},
            {"name": "read_file", "args": {"path": "/y"}, "id": "tc-y"},
        ]
        tm_x = ToolMessage(content="x contents", tool_call_id="tc-x")
        tm_y = ToolMessage(content="y contents", tool_call_id="tc-y")
        new_user = _human("next turn")
        for i, m in enumerate([ai, tm_x, tm_y, new_user]):
            m.id = f"m-{i}"

        remaining = [ai]
        preserved = [tm_x, tm_y, new_user]

        new_remaining, rescued_preserved = mw._rescue_tool_call_pairs(remaining, preserved)

        assert ai in rescued_preserved
        assert ai not in new_remaining
        # AI must precede both ToolMessages for Anthropic.
        assert rescued_preserved.index(ai) < rescued_preserved.index(tm_x)
        assert rescued_preserved.index(ai) < rescued_preserved.index(tm_y)

    def test_coherence_warning_logged_when_orphan_cannot_be_rescued(self, caplog):
        """If the matching counterpart is in neither remaining nor preserved
        (e.g. it was never recorded), _assert_tool_pair_coherence logs a
        WARNING. The list is not modified — strip is left to a follow-up."""
        mw = _make_mw()
        caplog.set_level("WARNING")
        ai_orphan = AIMessage(content="")
        ai_orphan.tool_calls = [{"name": "read_file", "args": {"path": "/z"}, "id": "tc-ghost"}]
        ai_orphan.id = "ai-orphan"
        plain = _human("ok")
        plain.id = "plain"

        mw._assert_tool_pair_coherence([ai_orphan, plain])

        assert "orphan tool_call pairs" in caplog.text
        assert "tc-ghost" in caplog.text

    def test_partition_with_skill_rescue_keeps_pairs_coherent(self):
        """End-to-end through _partition_with_skill_rescue: a tool_use/tool_result
        split across cutoff must come out paired."""
        mw = _make_mw()
        ai_with_tc, tool_result = _ai_tool("/tmp/d.txt")
        final_ai = AIMessage(content="done")
        msgs = [ai_with_tc, tool_result, final_ai]
        for i, m in enumerate(msgs):
            m.id = f"m-{i}"

        # Cutoff at 1 → tool_use goes to summarize, tool_result stays preserved.
        to_summarize, preserved = mw._partition_with_skill_rescue(msgs, cutoff_index=1)

        preserved_call_ids = mw._tool_call_ids(ai_with_tc) if ai_with_tc in preserved else set()
        preserved_result_ids = {
            getattr(m, "tool_call_id", None)
            for m in preserved
            if isinstance(m, ToolMessage)
        } - {None}

        # After rescue, every preserved tool_result must have a matching tool_use.
        assert preserved_result_ids.issubset(preserved_call_ids), (
            f"Orphan tool_result remains: preserved={preserved}"
        )


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

        state = {"messages": [*to_summarize, *preserved]}
        mw._fire_hooks(state, to_summarize, preserved, rt)

        assert len(fired_events) == 1
        event = fired_events[0]
        assert event.thread_id == "t-hook"
        assert event.agent_name == "agent-1"
        assert event.state is state
        assert len(event.messages_to_summarize) == 1
        assert len(event.preserved_messages) == 1

    def test_hook_failure_does_not_propagate(self):
        def bad_hook(event: SummarizationEvent) -> None:
            raise RuntimeError("hook error")

        mw = _make_mw(hooks=[bad_hook])
        # Should not raise
        mw._fire_hooks({"messages": []}, [_human("a")], [_human("b")], _runtime())

    def test_multiple_hooks_all_called(self):
        called = []
        mw = _make_mw(hooks=[lambda e: called.append("h1"), lambda e: called.append("h2")])
        mw._fire_hooks({"messages": []}, [_human("a")], [], _runtime())
        assert called == ["h1", "h2"]

    def test_no_hooks_no_error(self):
        mw = _make_mw(hooks=[])
        mw._fire_hooks({"messages": []}, [], [], _runtime())  # should not raise

    def test_preserved_budget_warning_after_rescue(self, caplog):
        mw = _make_mw()
        mw._last_trigger_threshold = 10

        with caplog.at_level("WARNING"):
            mw._warn_if_preserved_over_budget([_human("a"), _human("b")])

        assert "preserved window exceeds trigger threshold" in caplog.text


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


def test_default_summary_prompt_owned_by_capyhome_middleware():
    mw = _make_mw()

    assert mw.summary_prompt == DEFAULT_SUMMARY_PROMPT


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


def test_token_compaction_defers_once_for_fresh_tool_results():
    mw = _make_mw(trigger=("tokens", 20), keep=("tokens", 10))
    ai, tool = _ai_tool("report.md")
    messages = [_human("analyse"), ai, tool]
    for i, msg in enumerate(messages):
        msg.id = f"msg-{i}"
    state = {"messages": messages}

    result = mw.before_model(state, _runtime())

    assert result == {
        "deferred_compaction": True,
        "deferred_compaction_message_count": len(messages),
    }


def test_deferred_compaction_runs_on_next_user_turn():
    mw = _make_mw(trigger=("tokens", 20), keep=("tokens", 10))
    messages = [_human("analyse"), AIMessage(content="done"), _human("next question")]
    for i, msg in enumerate(messages):
        msg.id = f"msg-{i}"
    state = {"messages": messages, "deferred_compaction": True, "deferred_compaction_message_count": 2}

    result = mw.before_model(state, _runtime())

    assert result is not None
    assert result["deferred_compaction"] is False
    assert result["deferred_compaction_message_count"] is None
    assert "messages" in result


def test_deferred_compaction_grace_is_bounded():
    mw = _make_mw(trigger=("tokens", 20), keep=("tokens", 10))
    messages = [_human("analyse")]
    for i in range(6):
        _, tool = _ai_tool(f"report-{i}.md")
        messages.append(tool)
    for i, msg in enumerate(messages):
        msg.id = f"msg-{i}"
    state = {"messages": messages, "deferred_compaction": True, "deferred_compaction_message_count": 1}

    result = mw.before_model(state, _runtime())

    assert result is not None
    assert result["deferred_compaction"] is False
    assert result["deferred_compaction_message_count"] is None
    assert "messages" in result


def test_compaction_event_records_trigger_counts_and_summary_quality(monkeypatch):
    mw = _make_mw()
    emitted = []
    archived = []
    monkeypatch.setattr("src.agents.middlewares.summarization_middleware.append_runtime_event", lambda runtime, payload: emitted.append(payload))
    monkeypatch.setattr("src.agents.middlewares.summarization_middleware.append_compaction_entry", lambda thread_id, payload: archived.append((thread_id, payload)))

    mw._last_trigger_type = "messages"
    mw._last_trigger_threshold = 3
    mw._last_trigger_observed = 4
    mw._last_summary_quality = "fallback"
    mw._last_summary_source = "deterministic_state"
    mw._last_summary_error = "empty summary"

    mw._record_compaction_event(
        runtime=_runtime(thread_id="thread-compact"),
        summary="[summary]",
        compressed_count=3,
        kept_count=1,
    )

    assert emitted == [
        {
            "source": "summarization_middleware",
            "event": "compaction",
            "thread_id": "thread-compact",
            "messages_compressed": 3,
            "messages_kept": 1,
            "trigger": "messages",
            "trigger_threshold": 3,
            "trigger_observed": 4,
            "summary_quality": "fallback",
            "summary_source": "deterministic_state",
            "summary_error": "empty summary",
        }
    ]
    assert archived[0][0] == "thread-compact"
    assert archived[0][1]["summary_text"] == "[summary]"


def test_fraction_trigger_metadata_not_reported_without_proof():
    mw = _make_mw()
    mw._trigger_tuples = [("fraction", 0.8)]

    trigger = mw._detect_trigger_type([_human("a")], total_tokens=10)

    assert trigger == "threshold_unmet"


def test_memory_flush_hook_queues_tool_heavy_segments(monkeypatch):
    queued = {}
    monkeypatch.setattr("src.agents.memory.summarization_hook.get_memory_config", lambda: SimpleNamespace(enabled=True))

    class Queue:
        def queue_immediate(self, **kwargs):
            queued.update(kwargs)

    monkeypatch.setattr("src.agents.memory.summarization_hook.get_memory_queue", lambda: Queue())
    ai, tool = _ai_tool("report.md")
    event = SummarizationEvent(
        messages_to_summarize=(_human("analyse the report"), ai, tool),
        preserved_messages=(),
        thread_id="thread-tool-heavy",
        agent_name=None,
        runtime=_runtime("thread-tool-heavy"),
    )

    memory_flush_hook(event)

    assert queued["thread_id"] == "thread-tool-heavy"
    assert any(getattr(msg, "type", None) == "ai" and "Tool-heavy segment" in str(msg.content) for msg in queued["messages"])
