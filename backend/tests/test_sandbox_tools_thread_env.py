from unittest.mock import MagicMock

from src.sandbox import tools as sandbox_tools


class _FakeSandbox:
    def __init__(self):
        self.commands: list[str] = []

    def execute_command(self, command: str) -> str:
        self.commands.append(command)
        return "ok"


def _runtime(thread_id: str | None) -> MagicMock:
    rt = MagicMock()
    rt.context = {"thread_id": thread_id} if thread_id is not None else {}
    rt.state = {"sandbox": {"sandbox_id": "local"}}
    return rt


def test_inject_thread_env_in_command_adds_both_vars():
    command = sandbox_tools.inject_thread_env_in_command("echo hello", "thread-123")
    assert command.startswith("CAPYBARA_HOME_THREAD_ID=thread-123 THREAD_ID=thread-123 ")
    assert command.endswith("echo hello")


def test_bash_tool_injects_thread_env_per_invocation(monkeypatch):
    fake = _FakeSandbox()

    monkeypatch.setattr(sandbox_tools, "ensure_sandbox_initialized", lambda runtime: fake)
    monkeypatch.setattr(sandbox_tools, "ensure_thread_directories_exist", lambda runtime: None)
    monkeypatch.setattr(sandbox_tools, "is_local_sandbox", lambda runtime: False)

    runtime = _runtime("thread-abc")
    result = sandbox_tools.bash_tool.func(runtime=runtime, description="check env", command="echo $CAPYBARA_HOME_THREAD_ID")

    assert result == "ok"
    assert len(fake.commands) == 1
    assert fake.commands[0].startswith("CAPYBARA_HOME_THREAD_ID=thread-abc THREAD_ID=thread-abc ")
    assert fake.commands[0].endswith("echo $CAPYBARA_HOME_THREAD_ID")


def test_thread_env_does_not_leak_between_calls(monkeypatch):
    fake = _FakeSandbox()

    monkeypatch.setattr(sandbox_tools, "ensure_sandbox_initialized", lambda runtime: fake)
    monkeypatch.setattr(sandbox_tools, "ensure_thread_directories_exist", lambda runtime: None)
    monkeypatch.setattr(sandbox_tools, "is_local_sandbox", lambda runtime: False)

    runtime_a = _runtime("thread-a")
    runtime_b = _runtime("thread-b")

    sandbox_tools.bash_tool.func(runtime=runtime_a, description="cmd a", command="echo A")
    sandbox_tools.bash_tool.func(runtime=runtime_b, description="cmd b", command="echo B")

    assert len(fake.commands) == 2
    assert "CAPYBARA_HOME_THREAD_ID=thread-a THREAD_ID=thread-a" in fake.commands[0]
    assert "CAPYBARA_HOME_THREAD_ID=thread-b THREAD_ID=thread-b" in fake.commands[1]
