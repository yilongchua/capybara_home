from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from src.control_plane.redaction import RedactionService


def _backend_prompt_root() -> Path:
    return Path(__file__).resolve().parents[2] / "prompts"


def _jinja_env(prompt_dir: Path) -> Environment:
    return Environment(
        loader=FileSystemLoader(prompt_dir),
        undefined=StrictUndefined,
        autoescape=False,
        trim_blocks=True,
        lstrip_blocks=True,
    )


class CIDMask:
    """Deterministic CID masking plus Jinja2 prompt rendering."""

    def __init__(self, prompt_dir: Path | None = None) -> None:
        self._redaction = RedactionService()
        self._prompt_dir = prompt_dir or (_backend_prompt_root() / "cid_mask")
        self._env = _jinja_env(self._prompt_dir)

    def mask_text(self, text: str) -> str:
        """Mask sensitive values deterministically and return the masked string."""
        return self._redaction.redact_text(text)

    def render_prompt(self, *, input_text: str, replace_with: str = "[REDACTED]") -> dict[str, str]:
        """Render system/user prompts for LLM-based masking flows."""
        system = self._env.get_template("system.j2").render(
            replace_with=replace_with,
            input_text=input_text,
        )
        user = self._env.get_template("user.j2").render(
            input_text=input_text,
        )
        return {"system": system, "user": user}


class CSVInterpreter:
    """CSV / Excel / Google Sheets interpreter with Jinja2 prompt rendering."""

    def __init__(self, prompt_dir: Path | None = None) -> None:
        self._prompt_dir = prompt_dir or (_backend_prompt_root() / "csv_interpreter")
        self._env = _jinja_env(self._prompt_dir)

    def interpret(self, source: str, *, max_rows: int = 10) -> dict[str, Any]:

        resolved_source = self._normalize_source(source)
        df = self._load_dataframe(resolved_source)

        df_head = df.head(max_rows)
        missing_counts = df.isna().sum().to_dict()
        missing_pct = {
            key: float(value) / max(len(df), 1) for key, value in missing_counts.items()
        }

        columns = []
        for col in df.columns:
            series = df[col]
            dtype = str(series.dtype)
            sample_values = [
                value for value in series.head(max_rows).tolist() if value is not None
            ]
            columns.append(
                {
                    "name": str(col),
                    "dtype": dtype,
                    "missing_count": int(missing_counts.get(col, 0)),
                    "missing_pct": round(missing_pct.get(col, 0.0), 4),
                    "sample_values": sample_values[:5],
                    "meaning_hint": self._column_hint(str(col)),
                }
            )

        brief = {
            "source": resolved_source,
            "shape": {"rows": int(df.shape[0]), "columns": int(df.shape[1])},
            "missing_by_column": {
                str(col): int(count) for col, count in missing_counts.items()
            },
            "columns": columns,
            "preview_rows": df_head.to_dict(orient="records"),
        }
        return brief

    def render_prompt(
        self,
        *,
        brief: dict[str, Any],
        domain_context: str = "",
    ) -> dict[str, str]:
        system = self._env.get_template("system.j2").render(
            domain_context=domain_context,
            output_schema=json.dumps(self._output_schema(), indent=2),
        )
        user = self._env.get_template("user.j2").render(
            brief=json.dumps(brief, indent=2, ensure_ascii=False),
        )
        return {"system": system, "user": user}

    def _normalize_source(self, source: str) -> str:
        if source.startswith("http") and "docs.google.com/spreadsheets" in source:
            parsed = urlparse(source)
            sheet_id = parsed.path.split("/d/")[-1].split("/")[0]
            qs = parse_qs(parsed.query)
            gid = qs.get("gid", ["0"])[0]
            return f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv&gid={gid}"
        return source

    def _load_dataframe(self, source: str):
        import pandas as pd

        if source.startswith("http"):
            return pd.read_csv(source)

        path = Path(source).expanduser().resolve()
        if not path.exists():
            raise FileNotFoundError(f"File not found: {path}")
        suffix = path.suffix.lower()
        if suffix in {".xls", ".xlsx"}:
            return pd.read_excel(path)
        return pd.read_csv(path)

    def _column_hint(self, name: str) -> str:
        lowered = name.lower()
        if "email" in lowered:
            return "likely email address"
        if "phone" in lowered or "mobile" in lowered:
            return "likely phone number"
        if lowered.endswith("id") or lowered.startswith("id_") or "_id" in lowered:
            return "likely identifier"
        if "date" in lowered or "time" in lowered:
            return "likely date/time"
        if "amount" in lowered or "price" in lowered or "total" in lowered:
            return "likely numeric amount"
        return "meaning requires domain context"

    def _output_schema(self) -> dict[str, Any]:
        return {
            "summary": "Short paragraph describing the dataset and key issues.",
            "columns": [
                {
                    "name": "column_name",
                    "meaning": "What the column represents in business terms",
                    "data_type": "e.g. string, integer, float, date",
                    "missing": "count of missing values",
                }
            ],
            "shape": {"rows": 0, "columns": 0},
            "missing_by_column": {"column_name": 0},
            "data_quality_flags": ["list of issues or anomalies"],
        }
