import threading
import time

from src.agents.memory.queue import ConversationContext, MemoryUpdateQueue


def test_memory_update_queue_serializes_same_scope_updates(monkeypatch):
    active: dict[str, int] = {"global": 0, "workspace": 0}
    max_active: dict[str, int] = {"global": 0, "workspace": 0}
    guard = threading.Lock()

    class FakeUpdater:
        def update_memory(self, *, scope: str, **_kwargs):
            with guard:
                active[scope] += 1
                max_active[scope] = max(max_active[scope], active[scope])
            time.sleep(0.02)
            with guard:
                active[scope] -= 1
            return True

    monkeypatch.setattr("src.agents.memory.updater.MemoryUpdater", FakeUpdater)

    queue = MemoryUpdateQueue()
    context = ConversationContext(thread_id="thread-1", messages=[object()], agent_name="agent-a", workspace_id="workspace-a")
    threads = [threading.Thread(target=queue._update_context_memory, args=(context,)) for _ in range(4)]

    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert max_active == {"global": 1, "workspace": 1}
