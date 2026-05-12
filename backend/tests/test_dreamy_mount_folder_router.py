from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.config.paths import Paths
from src.gateway.routers import dreamy


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    paths = Paths(tmp_path)
    monkeypatch.setattr(dreamy, "get_paths", lambda: paths)
    app = FastAPI()
    app.include_router(dreamy.router)
    with TestClient(app) as test_client:
        yield test_client, paths


def test_mount_folder_put_get_delete_round_trip(client: tuple[TestClient, Paths], tmp_path: Path):
    test_client, paths = client
    thread_id = "thread_mount_round_trip"
    mounted_dir = (tmp_path / "mounted").resolve()
    mounted_dir.mkdir(parents=True, exist_ok=True)

    put_response = test_client.put(
        f"/api/threads/{thread_id}/dreamy/mount-folder",
        json={"path": str(mounted_dir)},
    )
    assert put_response.status_code == 200
    assert put_response.json() == {"path": str(mounted_dir)}

    get_response = test_client.get(f"/api/threads/{thread_id}/dreamy/mount-folder")
    assert get_response.status_code == 200
    assert get_response.json() == {"path": str(mounted_dir)}

    delete_response = test_client.delete(f"/api/threads/{thread_id}/dreamy/mount-folder")
    assert delete_response.status_code == 200
    assert delete_response.json() == {"path": None}

    get_after_delete = test_client.get(f"/api/threads/{thread_id}/dreamy/mount-folder")
    assert get_after_delete.status_code == 200
    assert get_after_delete.json() == {"path": None}

    assert not (paths.sandbox_user_data_dir(thread_id) / "dreamy_mount.json").exists()


def test_mount_folder_delete_when_missing_is_noop(client: tuple[TestClient, Paths]):
    test_client, _ = client
    response = test_client.delete("/api/threads/thread_mount_missing/dreamy/mount-folder")
    assert response.status_code == 200
    assert response.json() == {"path": None}
