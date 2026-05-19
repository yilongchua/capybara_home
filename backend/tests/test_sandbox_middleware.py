from types import SimpleNamespace

from src.sandbox.middleware import SandboxMiddleware


def test_sandbox_middleware_can_borrow_without_releasing(monkeypatch):
    released: list[str] = []

    monkeypatch.setattr(
        "src.sandbox.middleware.get_sandbox_provider",
        lambda: SimpleNamespace(release=lambda sandbox_id: released.append(sandbox_id)),
    )

    middleware = SandboxMiddleware(lazy_init=True, release_on_exit=False)
    middleware.after_agent({"sandbox": {"sandbox_id": "sandbox-parent"}}, SimpleNamespace(context={}))

    assert released == []


def test_sandbox_middleware_releases_owned_sandbox_by_default(monkeypatch):
    released: list[str] = []

    monkeypatch.setattr(
        "src.sandbox.middleware.get_sandbox_provider",
        lambda: SimpleNamespace(release=lambda sandbox_id: released.append(sandbox_id)),
    )

    middleware = SandboxMiddleware(lazy_init=True)
    middleware.after_agent({"sandbox": {"sandbox_id": "sandbox-owned"}}, SimpleNamespace(context={}))

    assert released == ["sandbox-owned"]
