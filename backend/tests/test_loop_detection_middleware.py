"""Tests for LoopDetectionMiddleware."""

from __future__ import annotations

from types import SimpleNamespace

from langchain_core.messages import AIMessage, HumanMessage

from src.agents.middlewares.loop_detection_middleware import (
    LoopDetectionMiddleware,
    _hash_tool_calls,
    _normalize_args,
    _stable_key,
)


def _runtime(thread_id: str = "t1"):
    return SimpleNamespace(context={"thread_id": thread_id})


def _ai(tool_calls=None, content=""):
    msg = AIMessage(content=content)
    if tool_calls:
        msg.tool_calls = tool_calls
    return msg


def _tc(name: str, **kwargs):
    return {"name": name, "args": kwargs, "id": f"id-{name}"}


# ---------------------------------------------------------------------------
# Hashing helpers
# ---------------------------------------------------------------------------


def test_normalize_args_dict():
    args, fb = _normalize_args({"path": "/foo"})
    assert args == {"path": "/foo"}
    assert fb is None


def test_normalize_args_json_string():
    args, fb = _normalize_args('{"query": "ai"}')
    assert args == {"query": "ai"}
    assert fb is None


def test_normalize_args_plain_string():
    args, fb = _normalize_args("not json")
    assert args == {}
    assert fb == "not json"


def test_normalize_args_none():
    args, fb = _normalize_args(None)
    assert args == {}
    assert fb is None


def test_stable_key_read_file_bucketing():
    key1 = _stable_key("read_file", {"path": "/f", "start_line": 1, "end_line": 199}, None)
    key2 = _stable_key("read_file", {"path": "/f", "start_line": 50, "end_line": 180}, None)
    assert key1 == key2, "reads within same 200-line bucket should hash the same"

    key3 = _stable_key("read_file", {"path": "/f", "start_line": 201}, None)
    assert key1 != key3, "reads in different buckets should hash differently"


def test_hash_tool_calls_order_independent():
    tc1 = [_tc("search", query="ai"), _tc("read_file", path="/a")]
    tc2 = [_tc("read_file", path="/a"), _tc("search", query="ai")]
    assert _hash_tool_calls(tc1) == _hash_tool_calls(tc2)


def test_hash_tool_calls_different_args():
    tc1 = [_tc("search", query="ai")]
    tc2 = [_tc("search", query="ml")]
    assert _hash_tool_calls(tc1) != _hash_tool_calls(tc2)


# ---------------------------------------------------------------------------
# Hash-based layer (identical call sets)
# ---------------------------------------------------------------------------


def test_no_detection_on_first_call():
    mw = LoopDetectionMiddleware(warn_threshold=3, hard_limit=5)
    state = {"messages": [_ai([_tc("search", query="ai")])]}
    result = mw.after_model(state, _runtime())
    assert result is None


def test_warning_injected_at_threshold(monkeypatch):
    mw = LoopDetectionMiddleware(warn_threshold=3, hard_limit=5)
    tc = [_tc("search", query="ai")]
    state = {"messages": [_ai(tc)]}
    rt = _runtime()

    # Fire 2 times — no warning yet
    for _ in range(2):
        result = mw.after_model(state, rt)
    assert result is None

    # 3rd time — warning injected
    result = mw.after_model(state, rt)
    assert result is not None
    injected = result["messages"]
    assert len(injected) == 1
    assert isinstance(injected[0], HumanMessage)
    assert "LOOP DETECTED" in injected[0].content


def test_warning_injected_once_per_hash():
    mw = LoopDetectionMiddleware(warn_threshold=3, hard_limit=10)
    tc = [_tc("search", query="ai")]
    state = {"messages": [_ai(tc)]}
    rt = _runtime()

    warnings = 0
    for _ in range(6):
        result = mw.after_model(state, rt)
        if result and "messages" in result and result["messages"]:
            # Hard stop returns modified AIMessage, not HumanMessage
            if isinstance(result["messages"][0], HumanMessage):
                warnings += 1
    assert warnings == 1


def test_hard_stop_strips_tool_calls():
    mw = LoopDetectionMiddleware(warn_threshold=3, hard_limit=5)
    tc = [_tc("search", query="ai")]
    msg = _ai(tc)
    msg.content = "thinking"
    state = {"messages": [msg]}
    rt = _runtime()

    for _ in range(5):
        result = mw.after_model(state, rt)

    assert result is not None
    updated_msg = result["messages"][0]
    assert updated_msg.tool_calls == []
    assert "FORCED STOP" in updated_msg.content


# ---------------------------------------------------------------------------
# Frequency-based layer (per tool-type saturation)
# ---------------------------------------------------------------------------


def test_freq_warning_at_threshold():
    mw = LoopDetectionMiddleware(tool_freq_warn=5, tool_freq_hard_limit=10)
    rt = _runtime("t-freq")

    for i in range(4):
        state = {"messages": [_ai([_tc("read_file", path=f"/file{i}")])]}
        result = mw.after_model(state, rt)

    # 5th call to read_file — frequency warning
    state = {"messages": [_ai([_tc("read_file", path="/file99")])]}
    result = mw.after_model(state, rt)
    assert result is not None
    assert isinstance(result["messages"][0], HumanMessage)
    assert "LOOP DETECTED" in result["messages"][0].content
    assert "read_file" in result["messages"][0].content


def test_freq_hard_stop():
    mw = LoopDetectionMiddleware(tool_freq_warn=5, tool_freq_hard_limit=8)
    rt = _runtime("t-freq-hard")

    for i in range(8):
        state = {"messages": [_ai([_tc("bash", command=f"ls /dir{i}")])]}
        mw.after_model(state, rt)

    state = {"messages": [_ai([_tc("bash", command="ls /dir_final")])]}
    result = mw.after_model(state, rt)
    assert result is not None
    msg = result["messages"][0]
    assert msg.tool_calls == []
    assert "FORCED STOP" in msg.content


# ---------------------------------------------------------------------------
# Thread isolation
# ---------------------------------------------------------------------------


def test_separate_threads_tracked_independently():
    mw = LoopDetectionMiddleware(warn_threshold=3, hard_limit=5)
    tc = [_tc("search", query="same")]

    for _ in range(2):
        mw.after_model({"messages": [_ai(tc)]}, _runtime("thread-A"))

    # Thread B hasn't crossed threshold yet
    result = mw.after_model({"messages": [_ai(tc)]}, _runtime("thread-B"))
    assert result is None


def test_reset_clears_state():
    mw = LoopDetectionMiddleware(warn_threshold=3, hard_limit=5)
    tc = [_tc("search", query="ai")]
    rt = _runtime("t-reset")

    for _ in range(3):
        mw.after_model({"messages": [_ai(tc)]}, rt)

    mw.reset("t-reset")

    # After reset, count starts from zero — no warning on first call
    result = mw.after_model({"messages": [_ai(tc)]}, rt)
    assert result is None


# ---------------------------------------------------------------------------
# Non-AI message ignored
# ---------------------------------------------------------------------------


def test_ignores_human_messages():
    mw = LoopDetectionMiddleware(warn_threshold=2)
    state = {"messages": [HumanMessage(content="hi")]}
    result = mw.after_model(state, _runtime())
    assert result is None


def test_resets_counters_on_new_real_user_message():
    mw = LoopDetectionMiddleware(warn_threshold=3, hard_limit=5)
    rt = _runtime("thread-reset-by-user")
    tc = [_tc("read_file", path="/a.py")]

    # Same user turn -> warning on 3rd repeated pattern.
    state_turn_1 = {
        "messages": [
            HumanMessage(content="analyse repo A"),
            _ai(tc),
        ]
    }
    mw.after_model(state_turn_1, rt)
    mw.after_model(state_turn_1, rt)
    warn = mw.after_model(state_turn_1, rt)
    assert warn is not None
    assert isinstance(warn["messages"][0], HumanMessage)

    # New real user message -> counters reset, so first pass should not warn.
    state_turn_2 = {
        "messages": [
            HumanMessage(content="analyse repo B"),
            _ai(tc),
        ]
    }
    first_after_new_user = mw.after_model(state_turn_2, rt)
    assert first_after_new_user is None
