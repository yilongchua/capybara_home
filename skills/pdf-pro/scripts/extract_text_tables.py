#!/usr/bin/env python3
"""Extract page text and table-like structures from a PDF into JSON."""

import argparse
import json
import os
import sys
from pathlib import Path

try:
    import pdfplumber
except ImportError:
    os.system(f"{sys.executable} -m pip install pdfplumber -q")
    import pdfplumber


def extract(path: Path) -> dict:
    result: dict[str, object] = {
        "file": str(path),
        "pages": [],
        "summary": {
            "page_count": 0,
            "tables_detected": 0,
        },
    }

    with pdfplumber.open(path) as pdf:
        result["summary"]["page_count"] = len(pdf.pages)
        for idx, page in enumerate(pdf.pages, start=1):
            text = page.extract_text() or ""
            tables = page.extract_tables() or []
            cleaned_tables = []
            for table in tables:
                cleaned_rows = [["" if cell is None else str(cell) for cell in row] for row in table]
                cleaned_tables.append(cleaned_rows)

            result["summary"]["tables_detected"] += len(cleaned_tables)
            result["pages"].append(
                {
                    "page": idx,
                    "text": text,
                    "tables": cleaned_tables,
                }
            )

    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Extract text and tables from PDF")
    parser.add_argument("--input", required=True, help="Input PDF path")
    parser.add_argument("--output", required=False, help="Optional output JSON path")
    args = parser.parse_args()

    in_path = Path(args.input)
    if not in_path.exists():
        raise SystemExit(f"Input PDF not found: {in_path}")

    report = extract(in_path)
    rendered = json.dumps(report, ensure_ascii=False, indent=2)

    if args.output:
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(rendered, encoding="utf-8")
        print(f"Saved extraction report to {out_path}")
    else:
        print(rendered)


if __name__ == "__main__":
    main()
