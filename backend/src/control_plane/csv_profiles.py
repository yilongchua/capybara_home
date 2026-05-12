from __future__ import annotations

from pathlib import Path
from typing import Any

import duckdb

from src.config import get_app_config
from src.control_plane.redaction import RedactionService


def _escape_sql_path(path: Path) -> str:
    return str(path).replace("'", "''")


class CSVProfileService:
    def __init__(self) -> None:
        self._config = get_app_config().csv_profiles
        self._redaction = RedactionService()

    def get_profile(self, profile_id: str | None) -> dict[str, Any] | None:
        if not profile_id:
            return None
        for profile in self._config.profiles:
            if profile.id == profile_id:
                return profile.model_dump(mode="json")
        return None

    def analyze(self, csv_path: str | Path, profile_id: str | None = None) -> dict[str, Any]:
        path = Path(csv_path).expanduser().resolve()
        if not path.exists():
            raise FileNotFoundError(f"CSV file not found: {path}")
        if not self._config.enabled:
            raise RuntimeError("CSV profiles are disabled")

        profile = next((item for item in self._config.profiles if item.id == profile_id), None)
        row_limit = profile.row_limit if profile else 25
        sample_rows = profile.sample_rows if profile else 5
        select_columns = profile.select_columns if profile else []
        redact_columns = set(profile.redact_columns if profile else [])

        conn = duckdb.connect(database=":memory:")
        escaped_path = _escape_sql_path(path)
        conn.execute(f"CREATE VIEW csv_data AS SELECT * FROM read_csv_auto('{escaped_path}', ALL_VARCHAR=TRUE)")

        columns = conn.execute("DESCRIBE csv_data").fetchall()
        column_names = [row[0] for row in columns]
        selected = select_columns or column_names
        projection = ", ".join(f'"{column}"' for column in selected)
        row_count = conn.execute("SELECT COUNT(*) FROM csv_data").fetchone()[0]
        preview_rows = conn.execute(f"SELECT {projection} FROM csv_data LIMIT {max(sample_rows, 1)}").fetchall()
        preview: list[dict[str, Any]] = []
        for row in preview_rows:
            item = dict(zip(selected, row, strict=False))
            for column in list(item.keys()):
                if column in redact_columns:
                    item[column] = self._redaction.redact_value(item[column])
            preview.append(item)

        summary_lines = [
            f"Rows scanned: {row_count}",
            f"Columns: {', '.join(column_names)}",
        ]
        if profile and profile.focus:
            summary_lines.append(f"Focus: {profile.focus}")
        if profile and profile.summary_instructions:
            summary_lines.append(f"Profile instructions: {profile.summary_instructions}")

        return {
            "path": str(path),
            "profile_id": profile.id if profile else None,
            "description": profile.description if profile else "",
            "row_count": int(row_count),
            "columns": column_names,
            "selected_columns": selected,
            "preview": preview,
            "summary": "\n".join(summary_lines[:row_limit]),
        }
