#!/usr/bin/env python3
"""OCR a scanned PDF by rendering pages to images and running Tesseract."""

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

try:
    import pytesseract
except ImportError:
    os.system(f"{sys.executable} -m pip install pytesseract -q")
    import pytesseract

try:
    from PIL import Image
except ImportError:
    os.system(f"{sys.executable} -m pip install pillow -q")
    from PIL import Image


def _require_binary(name: str) -> str:
    path = shutil.which(name)
    if not path:
        raise RuntimeError(f"Missing system dependency: {name}. Please install it in the runtime environment.")
    return path


def run_ocr(input_pdf: Path) -> str:
    _require_binary("pdftoppm")
    _require_binary("tesseract")

    with tempfile.TemporaryDirectory(prefix="pdf-ocr-") as tmp_dir:
        tmp = Path(tmp_dir)
        image_prefix = tmp / "page"

        render_cmd = [
            "pdftoppm",
            "-png",
            str(input_pdf),
            str(image_prefix),
        ]
        render = subprocess.run(render_cmd, capture_output=True, text=True)
        if render.returncode != 0:
            raise RuntimeError(f"pdftoppm failed: {render.stderr.strip()}")

        page_images = sorted(tmp.glob("page-*.png"))
        if not page_images:
            raise RuntimeError("No rendered page images found; OCR aborted.")

        chunks: list[str] = []
        for idx, image_path in enumerate(page_images, start=1):
            with Image.open(image_path) as img:
                text = pytesseract.image_to_string(img)
            chunks.append(f"## Page {idx}\n\n{text.strip()}\n")

        return "\n".join(chunks).strip()


def main() -> None:
    parser = argparse.ArgumentParser(description="OCR a scanned PDF with Tesseract")
    parser.add_argument("--input", required=True, help="Input PDF path")
    parser.add_argument("--output", required=True, help="Output Markdown path")
    args = parser.parse_args()

    in_path = Path(args.input)
    out_path = Path(args.output)

    if not in_path.exists():
        raise SystemExit(f"Input PDF not found: {in_path}")

    text = run_ocr(in_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(text, encoding="utf-8")
    print(f"Saved OCR output to {out_path}")


if __name__ == "__main__":
    main()
