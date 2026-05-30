"""Core behaviour tests for UploadsMiddleware.

Covers:
- _files_from_kwargs: parsing, validation, existence check, virtual-path construction
- _create_files_message: output format with new-only and new+historical files
- before_agent: full injection pipeline (string & list content, preserved
  additional_kwargs, historical files from uploads dir, edge-cases)
"""

from pathlib import Path
from unittest.mock import MagicMock

from langchain_core.messages import AIMessage, HumanMessage

from src.agents.middlewares.uploads_middleware import UploadsMiddleware
from src.config.paths import Paths

THREAD_ID = "thread-abc123"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _middleware(tmp_path: Path) -> UploadsMiddleware:
    return UploadsMiddleware(base_dir=str(tmp_path))


def _runtime(thread_id: str | None = THREAD_ID) -> MagicMock:
    rt = MagicMock()
    rt.context = {"thread_id": thread_id}
    return rt


def _uploads_dir(tmp_path: Path, thread_id: str = THREAD_ID) -> Path:
    d = Paths(str(tmp_path)).sandbox_uploads_dir(thread_id)
    d.mkdir(parents=True, exist_ok=True)
    return d


def _human(content, files=None, **extra_kwargs):
    additional_kwargs = dict(extra_kwargs)
    if files is not None:
        additional_kwargs["files"] = files
    return HumanMessage(content=content, additional_kwargs=additional_kwargs)


# ---------------------------------------------------------------------------
# _files_from_kwargs
# ---------------------------------------------------------------------------


class TestFilesFromKwargs:
    def test_returns_none_when_files_field_absent(self, tmp_path):
        mw = _middleware(tmp_path)
        msg = HumanMessage(content="hello")
        assert mw._files_from_kwargs(msg) is None

    def test_returns_none_for_empty_files_list(self, tmp_path):
        mw = _middleware(tmp_path)
        msg = _human("hello", files=[])
        assert mw._files_from_kwargs(msg) is None

    def test_returns_none_for_non_list_files(self, tmp_path):
        mw = _middleware(tmp_path)
        msg = _human("hello", files="not-a-list")
        assert mw._files_from_kwargs(msg) is None

    def test_skips_non_dict_entries(self, tmp_path):
        mw = _middleware(tmp_path)
        msg = _human("hi", files=["bad", 42, None])
        assert mw._files_from_kwargs(msg) is None

    def test_skips_entries_with_empty_filename(self, tmp_path):
        mw = _middleware(tmp_path)
        msg = _human("hi", files=[{"filename": "", "size": 100, "path": "/mnt/user-data/workspace/uploads/x"}])
        assert mw._files_from_kwargs(msg) is None

    def test_always_uses_virtual_path(self, tmp_path):
        """path field must be /mnt/user-data/workspace/uploads/<filename> regardless of what the frontend sent."""
        mw = _middleware(tmp_path)
        msg = _human(
            "hi",
            files=[{"filename": "report.pdf", "size": 1024, "path": "/some/arbitrary/path/report.pdf"}],
        )
        result = mw._files_from_kwargs(msg)
        assert result is not None
        assert result[0]["path"] == "/mnt/user-data/workspace/uploads/report.pdf"

    def test_skips_file_that_does_not_exist_on_disk(self, tmp_path):
        mw = _middleware(tmp_path)
        uploads_dir = _uploads_dir(tmp_path)
        # file is NOT written to disk
        msg = _human("hi", files=[{"filename": "missing.txt", "size": 50, "path": "/mnt/user-data/workspace/uploads/missing.txt"}])
        assert mw._files_from_kwargs(msg, uploads_dir) is None

    def test_accepts_file_that_exists_on_disk(self, tmp_path):
        mw = _middleware(tmp_path)
        uploads_dir = _uploads_dir(tmp_path)
        (uploads_dir / "data.csv").write_text("a,b,c")
        msg = _human("hi", files=[{"filename": "data.csv", "size": 5, "path": "/mnt/user-data/workspace/uploads/data.csv"}])
        result = mw._files_from_kwargs(msg, uploads_dir)
        assert result is not None
        assert len(result) == 1
        assert result[0]["filename"] == "data.csv"
        assert result[0]["path"] == "/mnt/user-data/workspace/uploads/data.csv"

    def test_skips_nonexistent_but_accepts_existing_in_mixed_list(self, tmp_path):
        mw = _middleware(tmp_path)
        uploads_dir = _uploads_dir(tmp_path)
        (uploads_dir / "present.txt").write_text("here")
        msg = _human(
            "hi",
            files=[
                {"filename": "present.txt", "size": 4, "path": "/mnt/user-data/workspace/uploads/present.txt"},
                {"filename": "gone.txt", "size": 4, "path": "/mnt/user-data/workspace/uploads/gone.txt"},
            ],
        )
        result = mw._files_from_kwargs(msg, uploads_dir)
        assert result is not None
        assert [f["filename"] for f in result] == ["present.txt"]

    def test_no_existence_check_when_uploads_dir_is_none(self, tmp_path):
        """Without an uploads_dir argument the existence check is skipped entirely."""
        mw = _middleware(tmp_path)
        msg = _human("hi", files=[{"filename": "phantom.txt", "size": 10, "path": "/mnt/user-data/workspace/uploads/phantom.txt"}])
        result = mw._files_from_kwargs(msg, uploads_dir=None)
        assert result is not None
        assert result[0]["filename"] == "phantom.txt"

    def test_size_is_coerced_to_int(self, tmp_path):
        mw = _middleware(tmp_path)
        msg = _human("hi", files=[{"filename": "f.txt", "size": "2048", "path": "/mnt/user-data/workspace/uploads/f.txt"}])
        result = mw._files_from_kwargs(msg)
        assert result is not None
        assert result[0]["size"] == 2048

    def test_missing_size_defaults_to_zero(self, tmp_path):
        mw = _middleware(tmp_path)
        msg = _human("hi", files=[{"filename": "f.txt", "path": "/mnt/user-data/workspace/uploads/f.txt"}])
        result = mw._files_from_kwargs(msg)
        assert result is not None
        assert result[0]["size"] == 0


# ---------------------------------------------------------------------------
# _create_files_message
# ---------------------------------------------------------------------------


class TestCreateFilesMessage:
    def _new_file(self, filename="notes.txt", size=1024):
        return {"filename": filename, "size": size, "path": f"/mnt/user-data/workspace/uploads/{filename}"}

    def test_new_files_section_always_present(self, tmp_path):
        mw = _middleware(tmp_path)
        msg = mw._create_files_message([self._new_file()], [])
        assert "<uploaded_files>" in msg
        assert "</uploaded_files>" in msg
        assert "uploaded in this message" in msg
        assert "notes.txt" in msg
        assert "/mnt/user-data/workspace/uploads/notes.txt" in msg

    def test_historical_section_present_only_when_non_empty(self, tmp_path):
        mw = _middleware(tmp_path)

        msg_no_hist = mw._create_files_message([self._new_file()], [])
        assert "previous messages" not in msg_no_hist

        hist = self._new_file("old.txt")
        msg_with_hist = mw._create_files_message([self._new_file()], [hist])
        assert "previous messages" in msg_with_hist
        assert "old.txt" in msg_with_hist

    def test_size_formatting_kb(self, tmp_path):
        mw = _middleware(tmp_path)
        msg = mw._create_files_message([self._new_file(size=2048)], [])
        assert "2.0 KB" in msg

    def test_size_formatting_mb(self, tmp_path):
        mw = _middleware(tmp_path)
        msg = mw._create_files_message([self._new_file(size=2 * 1024 * 1024)], [])
        assert "2.0 MB" in msg

    def test_read_file_instruction_included(self, tmp_path):
        mw = _middleware(tmp_path)
        msg = mw._create_files_message([self._new_file()], [])
        assert "read_file" in msg

    def test_empty_new_files_produces_empty_marker(self, tmp_path):
        mw = _middleware(tmp_path)
        msg = mw._create_files_message([], [])
        assert "(empty)" in msg
        assert "<uploaded_files>" in msg
        assert "</uploaded_files>" in msg


# ---------------------------------------------------------------------------
# before_agent
# ---------------------------------------------------------------------------


class _FakeRequest:
    """Minimal stand-in for ModelRequest that supports `.override(messages=...)`."""

    def __init__(self, messages, runtime):
        self.messages = list(messages)
        self.runtime = runtime
        self.state = {}

    def override(self, messages=None, **_):
        new = _FakeRequest(messages if messages is not None else self.messages, self.runtime)
        new.state = self.state
        return new


def _run_wrap_model_call(mw, msg, runtime):
    """Helper: invoke wrap_model_call and return the messages the handler saw."""
    request = _FakeRequest([msg], runtime)
    captured: dict = {}

    def handler(req):
        captured["messages"] = list(req.messages)
        return "ok"

    mw.wrap_model_call(request, handler)
    return captured["messages"]


class TestBeforeAgent:
    """`before_agent` now ONLY records uploads in state — message mutation moved
    to `wrap_model_call` (#20 — ephemeral injection)."""

    def _state(self, *messages):
        return {"messages": list(messages)}

    def test_returns_none_when_messages_empty(self, tmp_path):
        mw = _middleware(tmp_path)
        assert mw.before_agent({"messages": []}, _runtime()) is None

    def test_returns_none_when_last_message_is_not_human(self, tmp_path):
        mw = _middleware(tmp_path)
        state = self._state(HumanMessage(content="q"), AIMessage(content="a"))
        assert mw.before_agent(state, _runtime()) is None

    def test_returns_none_when_no_files_in_kwargs(self, tmp_path):
        mw = _middleware(tmp_path)
        state = self._state(_human("plain message"))
        assert mw.before_agent(state, _runtime()) is None

    def test_returns_none_when_all_files_missing_from_disk(self, tmp_path):
        mw = _middleware(tmp_path)
        _uploads_dir(tmp_path)  # directory exists but is empty
        msg = _human("hi", files=[{"filename": "ghost.txt", "size": 10, "path": "/mnt/user-data/workspace/uploads/ghost.txt"}])
        state = self._state(msg)
        assert mw.before_agent(state, _runtime()) is None

    def test_records_new_files_in_state_only(self, tmp_path):
        """`before_agent` does NOT mutate messages — only stores uploads in state."""
        mw = _middleware(tmp_path)
        uploads_dir = _uploads_dir(tmp_path)
        (uploads_dir / "report.pdf").write_bytes(b"pdf")

        msg = _human("please analyse", files=[{"filename": "report.pdf", "size": 3, "path": "/mnt/user-data/workspace/uploads/report.pdf"}])
        result = mw.before_agent(self._state(msg), _runtime())

        assert result is not None
        assert "messages" not in result, "before_agent must not return a messages update"
        assert result["uploaded_files"] == [
            {
                "filename": "report.pdf",
                "size": 3,
                "path": "/mnt/user-data/workspace/uploads/report.pdf",
                "extension": ".pdf",
            }
        ]


class TestEphemeralInjection:
    """The `<uploaded_files>` block is injected per-LLM-call via wrap_model_call
    and never persisted into thread state."""

    def test_injects_uploaded_files_tag_into_string_content(self, tmp_path):
        mw = _middleware(tmp_path)
        uploads_dir = _uploads_dir(tmp_path)
        (uploads_dir / "report.pdf").write_bytes(b"pdf")

        msg = _human("please analyse", files=[{"filename": "report.pdf", "size": 3, "path": "/mnt/user-data/workspace/uploads/report.pdf"}])
        messages = _run_wrap_model_call(mw, msg, _runtime())
        injected = messages[-1]
        assert isinstance(injected.content, str)
        assert "<uploaded_files>" in injected.content
        assert "report.pdf" in injected.content
        assert "please analyse" in injected.content

    def test_injects_uploaded_files_tag_into_list_content(self, tmp_path):
        mw = _middleware(tmp_path)
        uploads_dir = _uploads_dir(tmp_path)
        (uploads_dir / "data.csv").write_bytes(b"a,b")

        msg = _human(
            [{"type": "text", "text": "analyse this"}],
            files=[{"filename": "data.csv", "size": 3, "path": "/mnt/user-data/workspace/uploads/data.csv"}],
        )
        messages = _run_wrap_model_call(mw, msg, _runtime())
        injected = messages[-1]
        assert "<uploaded_files>" in injected.content
        assert "analyse this" in injected.content

    def test_preserves_additional_kwargs_on_injected_message(self, tmp_path):
        mw = _middleware(tmp_path)
        uploads_dir = _uploads_dir(tmp_path)
        (uploads_dir / "img.png").write_bytes(b"png")

        files_meta = [{"filename": "img.png", "size": 3, "path": "/mnt/user-data/workspace/uploads/img.png", "status": "uploaded"}]
        msg = _human("check image", files=files_meta, element="task")
        messages = _run_wrap_model_call(mw, msg, _runtime())
        injected_kwargs = messages[-1].additional_kwargs
        assert injected_kwargs.get("files") == files_meta
        assert injected_kwargs.get("element") == "task"

    def test_does_not_mutate_original_message(self, tmp_path):
        """Ephemeral means ephemeral: the message object in `state` (and the
        request.messages list passed in) must not be mutated."""
        mw = _middleware(tmp_path)
        uploads_dir = _uploads_dir(tmp_path)
        (uploads_dir / "x.txt").write_bytes(b"x")

        msg = _human("user question", files=[{"filename": "x.txt", "size": 1, "path": "/mnt/user-data/workspace/uploads/x.txt"}])
        original_content = msg.content
        _run_wrap_model_call(mw, msg, _runtime())
        assert msg.content == original_content, "the original HumanMessage must not be mutated"

    def test_historical_files_from_uploads_dir_excluding_new(self, tmp_path):
        mw = _middleware(tmp_path)
        uploads_dir = _uploads_dir(tmp_path)
        (uploads_dir / "old.txt").write_bytes(b"old")
        (uploads_dir / "new.txt").write_bytes(b"new")

        msg = _human("go", files=[{"filename": "new.txt", "size": 3, "path": "/mnt/user-data/workspace/uploads/new.txt"}])
        messages = _run_wrap_model_call(mw, msg, _runtime())
        content = messages[-1].content
        assert "uploaded in this message" in content
        assert "new.txt" in content
        assert "previous messages" in content
        assert "old.txt" in content

    def test_no_historical_section_when_upload_dir_is_empty(self, tmp_path):
        mw = _middleware(tmp_path)
        uploads_dir = _uploads_dir(tmp_path)
        (uploads_dir / "only.txt").write_bytes(b"x")

        msg = _human("go", files=[{"filename": "only.txt", "size": 1, "path": "/mnt/user-data/workspace/uploads/only.txt"}])
        messages = _run_wrap_model_call(mw, msg, _runtime())
        content = messages[-1].content
        assert "previous messages" not in content

    def test_no_historical_scan_when_thread_id_is_none(self, tmp_path):
        mw = _middleware(tmp_path)
        msg = _human("go", files=[{"filename": "f.txt", "size": 1, "path": "/mnt/user-data/workspace/uploads/f.txt"}])
        messages = _run_wrap_model_call(mw, msg, _runtime(thread_id=None))
        content = messages[-1].content
        assert "previous messages" not in content

    def test_message_id_preserved_on_injected_message(self, tmp_path):
        mw = _middleware(tmp_path)
        uploads_dir = _uploads_dir(tmp_path)
        (uploads_dir / "f.txt").write_bytes(b"x")

        msg = _human("go", files=[{"filename": "f.txt", "size": 1, "path": "/mnt/user-data/workspace/uploads/f.txt"}])
        msg.id = "original-id-42"
        messages = _run_wrap_model_call(mw, msg, _runtime())
        assert messages[-1].id == "original-id-42"

    def test_no_double_injection_when_block_already_present(self, tmp_path):
        """Legacy threads where the old in-place mutation already baked the
        block into thread state must not get double-injected on top."""
        mw = _middleware(tmp_path)
        uploads_dir = _uploads_dir(tmp_path)
        (uploads_dir / "f.txt").write_bytes(b"x")

        msg = _human(
            "<uploaded_files>\nlegacy\n</uploaded_files>\n\nreal user text",
            files=[{"filename": "f.txt", "size": 1, "path": "/mnt/user-data/workspace/uploads/f.txt"}],
        )
        messages = _run_wrap_model_call(mw, msg, _runtime())
        assert messages[-1].content.count("<uploaded_files>") == 1
