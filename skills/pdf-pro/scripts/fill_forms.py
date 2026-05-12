#!/usr/bin/env python3
"""Fill AcroForm fields in a PDF from a JSON key/value file."""

import argparse
import json
import os
import sys
from pathlib import Path

try:
    from pypdf import PdfReader, PdfWriter
except ImportError:
    os.system(f"{sys.executable} -m pip install pypdf -q")
    from pypdf import PdfReader, PdfWriter


def fill_form(input_pdf: Path, field_values_path: Path, output_pdf: Path) -> int:
    values = json.loads(field_values_path.read_text(encoding="utf-8"))
    if not isinstance(values, dict):
        raise ValueError("field-values JSON must be an object of {fieldName: value}")

    reader = PdfReader(str(input_pdf))
    writer = PdfWriter()

    for page in reader.pages:
        writer.add_page(page)

    for i in range(len(writer.pages)):
        writer.update_page_form_field_values(writer.pages[i], values)

    output_pdf.parent.mkdir(parents=True, exist_ok=True)
    with output_pdf.open("wb") as fh:
        writer.write(fh)

    return len(values)


def main() -> None:
    parser = argparse.ArgumentParser(description="Fill PDF form fields from JSON")
    parser.add_argument("--input", required=True, help="Input PDF path")
    parser.add_argument("--field-values", required=True, help="JSON file with form values")
    parser.add_argument("--output", required=True, help="Output PDF path")
    args = parser.parse_args()

    in_path = Path(args.input)
    values_path = Path(args.field_values)
    out_path = Path(args.output)

    if not in_path.exists():
        raise SystemExit(f"Input PDF not found: {in_path}")
    if not values_path.exists():
        raise SystemExit(f"Field values JSON not found: {values_path}")

    count = fill_form(in_path, values_path, out_path)
    print(f"Filled {count} field(s) and saved to {out_path}")


if __name__ == "__main__":
    main()
