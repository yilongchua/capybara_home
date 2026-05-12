import tempfile
import zipfile
from pathlib import Path

from fastapi import HTTPException

from src.gateway.routers.skills import _safe_extract_zip


def _create_zip(path: Path, files: dict[str, str]) -> None:
    with zipfile.ZipFile(path, "w") as zf:
        for name, content in files.items():
            zf.writestr(name, content)


def test_safe_extract_zip_blocks_path_traversal(tmp_path):
    archive_path = tmp_path / "bad.skill"
    _create_zip(archive_path, {"../evil.txt": "owned"})

    with tempfile.TemporaryDirectory() as extract_dir:
        with zipfile.ZipFile(archive_path, "r") as zf:
            try:
                _safe_extract_zip(zf, Path(extract_dir))
                assert False, "Expected path traversal entry to be rejected"
            except HTTPException as e:
                assert e.status_code == 400
                assert "Path traversal detected" in e.detail


def test_safe_extract_zip_extracts_normal_archive(tmp_path):
    archive_path = tmp_path / "ok.skill"
    _create_zip(archive_path, {"skill/SKILL.md": "---\nname: ok-skill\n---\n"})

    with tempfile.TemporaryDirectory() as extract_dir:
        extract_path = Path(extract_dir)
        with zipfile.ZipFile(archive_path, "r") as zf:
            _safe_extract_zip(zf, extract_path)

        skill_file = extract_path / "skill" / "SKILL.md"
        assert skill_file.exists()
        assert "ok-skill" in skill_file.read_text(encoding="utf-8")
