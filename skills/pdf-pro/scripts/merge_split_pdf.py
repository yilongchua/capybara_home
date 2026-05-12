#!/usr/bin/env python3
"""Merge or split PDFs using pypdf."""

import argparse
import os
import sys
from pathlib import Path

try:
    from pypdf import PdfReader, PdfWriter
except ImportError:
    os.system(f"{sys.executable} -m pip install pypdf -q")
    from pypdf import PdfReader, PdfWriter


def merge(inputs: list[Path], output: Path) -> None:
    writer = PdfWriter()
    for path in inputs:
        reader = PdfReader(str(path))
        for page in reader.pages:
            writer.add_page(page)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("wb") as fh:
        writer.write(fh)


def split(input_path: Path, output: Path, start_page: int, end_page: int) -> None:
    reader = PdfReader(str(input_path))
    page_count = len(reader.pages)
    if start_page < 1 or end_page < start_page or end_page > page_count:
        raise ValueError(f"Invalid page range: {start_page}-{end_page}, document has {page_count} pages")

    writer = PdfWriter()
    for i in range(start_page - 1, end_page):
        writer.add_page(reader.pages[i])

    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("wb") as fh:
        writer.write(fh)


def main() -> None:
    parser = argparse.ArgumentParser(description="Merge or split PDFs")
    parser.add_argument("--mode", choices=["merge", "split"], required=True)
    parser.add_argument("--output", required=True, help="Output PDF path")

    parser.add_argument("--inputs", nargs="+", help="Input PDFs for merge mode")
    parser.add_argument("--input", help="Input PDF for split mode")
    parser.add_argument("--start-page", type=int, help="Start page (1-based, split mode)")
    parser.add_argument("--end-page", type=int, help="End page (1-based, split mode)")
    args = parser.parse_args()

    out_path = Path(args.output)

    if args.mode == "merge":
        if not args.inputs or len(args.inputs) < 2:
            raise SystemExit("Merge mode requires at least two --inputs files")
        input_paths = [Path(p) for p in args.inputs]
        for p in input_paths:
            if not p.exists():
                raise SystemExit(f"Input PDF not found: {p}")
        merge(input_paths, out_path)
        print(f"Merged {len(input_paths)} PDFs into {out_path}")
        return

    if not args.input:
        raise SystemExit("Split mode requires --input")
    if args.start_page is None or args.end_page is None:
        raise SystemExit("Split mode requires --start-page and --end-page")

    in_path = Path(args.input)
    if not in_path.exists():
        raise SystemExit(f"Input PDF not found: {in_path}")

    split(in_path, out_path, args.start_page, args.end_page)
    print(f"Wrote split pages {args.start_page}-{args.end_page} to {out_path}")


if __name__ == "__main__":
    main()
