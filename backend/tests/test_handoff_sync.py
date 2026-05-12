"""Tests for handoff_sync virtual path translation (Finding #1 regression guard).

Verifies that sync_handoff_files_from_state correctly translates virtual /mnt/...
paths to physical thread-scoped paths before writing, rather than attempting to
write to the literal /mnt mountpoint (which is read-only in most environments).
"""

from __future__ import annotations

from pathlib import Path

from src.agents.middlewares.handoff_sync import sync_handoff_files_from_state


def _make_thread_data(tmp_path: Path) -> dict:
    outputs = tmp_path / "outputs"
    workspace = tmp_path / "workspace"
    outputs.mkdir(parents=True, exist_ok=True)
    workspace.mkdir(parents=True, exist_ok=True)
    return {
        "workspace_path": str(workspace),
        "uploads_path": str(tmp_path / "uploads"),
        "outputs_path": str(outputs),
        "mounted_path": None,
    }


def _base_state(tmp_path: Path, *, with_sprint: bool = False) -> dict:
    thread_data = _make_thread_data(tmp_path)
    plan_path = "/mnt/user-data/outputs/plan.md"
    state: dict = {
        "thread_data": thread_data,
        "plan": {
            "title": "Hotel Research",
            "summary": "Find hotel pricing in Tasmania",
            "plan_path": plan_path,
        },
        "todo_graph": {
            "nodes": [
                {"id": "todo-1", "content": "Search hotels", "status": "completed", "depends_on": []},
                {"id": "todo-2", "content": "Compile report", "status": "pending", "depends_on": ["todo-1"]},
            ],
            "ready_ids": ["todo-2"],
        },
    }
    if with_sprint:
        state["plan"]["sprint_contract_path"] = "/mnt/user-data/outputs/sprint_contract.md"
    return state


class TestVirtualPathTranslation:
    def test_plan_written_to_physical_path(self, tmp_path):
        state = _base_state(tmp_path)
        changed = sync_handoff_files_from_state(state)

        physical_plan = tmp_path / "outputs" / "plan.md"
        assert physical_plan.exists(), "plan.md must be written to the physical path"
        assert changed == ["/mnt/user-data/outputs/plan.md"]

    def test_plan_content_is_rendered(self, tmp_path):
        state = _base_state(tmp_path)
        sync_handoff_files_from_state(state)

        content = (tmp_path / "outputs" / "plan.md").read_text()
        assert "Hotel Research" in content
        assert "## Phased Implementation Steps" in content
        assert "**todo-1**: Search hotels" in content
        assert "Rationale:" in content

    def test_sprint_contract_written_to_physical_path(self, tmp_path):
        state = _base_state(tmp_path, with_sprint=True)
        changed = sync_handoff_files_from_state(state)

        physical_sprint = tmp_path / "outputs" / "sprint_contract.md"
        assert physical_sprint.exists(), "sprint_contract.md must be written to the physical path"
        assert "/mnt/user-data/outputs/sprint_contract.md" in changed

    def test_no_write_to_literal_mnt(self, tmp_path, monkeypatch):
        """Regression: _write_if_changed must never be called with a /mnt path."""
        written_paths: list[str] = []
        import src.agents.middlewares.handoff_sync as hs

        original = hs._write_if_changed

        def spy(path: str, content: str) -> bool:
            written_paths.append(path)
            return original(path, content)

        monkeypatch.setattr(hs, "_write_if_changed", spy)
        sync_handoff_files_from_state(_base_state(tmp_path, with_sprint=True))

        for p in written_paths:
            assert not p.startswith("/mnt"), (
                f"_write_if_changed called with unresolved virtual path: {p!r}"
            )

    def test_idempotent_write(self, tmp_path):
        """Second call with unchanged state returns empty changed list."""
        state = _base_state(tmp_path)
        sync_handoff_files_from_state(state)
        changed = sync_handoff_files_from_state(state)
        assert changed == [], "no-op second write should return empty list"

    def test_no_thread_data_returns_empty(self):
        """Graceful degradation when thread_data is absent (e.g. embedded/test contexts)."""
        state = {
            "thread_data": None,
            "plan": {
                "title": "Test",
                "summary": "",
                "plan_path": "/mnt/user-data/outputs/plan.md",
            },
            "todo_graph": {
                "nodes": [{"id": "t1", "content": "Do something", "status": "pending", "depends_on": []}],
            },
        }
        # Must not raise; returns [] since path cannot be resolved to a physical location
        result = sync_handoff_files_from_state(state)
        assert result == []

    def test_no_plan_returns_empty(self):
        state = {"thread_data": {}, "plan": None}
        assert sync_handoff_files_from_state(state) == []

    def test_no_nodes_returns_empty(self, tmp_path):
        state = {
            "thread_data": _make_thread_data(tmp_path),
            "plan": {
                "title": "Empty",
                "summary": "",
                "plan_path": "/mnt/user-data/outputs/plan.md",
            },
            "todo_graph": {"nodes": []},
        }
        assert sync_handoff_files_from_state(state) == []

    def test_physical_path_passthrough(self, tmp_path):
        """Paths that are already physical (non-virtual) are written as-is."""
        outputs = tmp_path / "outputs"
        outputs.mkdir(parents=True)
        physical_plan = str(outputs / "plan.md")
        state = {
            "thread_data": _make_thread_data(tmp_path),
            "plan": {
                "title": "Physical",
                "summary": "",
                "plan_path": physical_plan,
            },
            "todo_graph": {
                "nodes": [{"id": "t1", "content": "Task", "status": "pending", "depends_on": []}],
            },
        }
        changed = sync_handoff_files_from_state(state)
        assert Path(physical_plan).exists()
        assert changed == [physical_plan]
