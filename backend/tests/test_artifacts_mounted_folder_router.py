from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.config.paths import Paths
from src.gateway.routers import artifacts


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    paths = Paths(tmp_path)
    monkeypatch.setattr(artifacts, "get_paths", lambda: paths)
    app = FastAPI()
    app.include_router(artifacts.router)
    with TestClient(app) as test_client:
        yield test_client, paths


def test_get_mounted_artifact_file(client: tuple[TestClient, Paths], tmp_path: Path):
    test_client, paths = client
    thread_id = "thread_mounted_artifact"

    mounted_root = tmp_path / "mounted"
    mounted_root.mkdir(parents=True, exist_ok=True)
    target = mounted_root / "notes.md"
    target.write_text("# mounted file\n", encoding="utf-8")

    user_data = paths.sandbox_user_data_dir(thread_id)
    user_data.mkdir(parents=True, exist_ok=True)
    (user_data / "dreamy_mount.json").write_text(
        f'{{"path": "{mounted_root}"}}',
        encoding="utf-8",
    )

    response = test_client.get(
        f"/api/threads/{thread_id}/artifacts/mnt/user-data/mounted/notes.md",
    )
    assert response.status_code == 200
    assert response.text == "# mounted file\n"


def test_get_mounted_artifact_rejects_traversal(client: tuple[TestClient, Paths], tmp_path: Path):
    test_client, paths = client
    thread_id = "thread_mounted_traversal"

    mounted_root = tmp_path / "mounted"
    mounted_root.mkdir(parents=True, exist_ok=True)

    user_data = paths.sandbox_user_data_dir(thread_id)
    user_data.mkdir(parents=True, exist_ok=True)
    (user_data / "dreamy_mount.json").write_text(
        f'{{"path": "{mounted_root}"}}',
        encoding="utf-8",
    )

    response = test_client.get(
        f"/api/threads/{thread_id}/artifacts/mnt/user-data/mounted/%2e%2e/secret.txt",
    )
    assert response.status_code == 403
