#!/usr/bin/env python3
"""Force workbook recalculation using headless LibreOffice."""

import argparse
import shutil
import subprocess
import tempfile
from pathlib import Path


def recalc(input_path: Path, output_path: Path) -> Path:
    soffice = shutil.which("soffice")
    if not soffice:
        raise RuntimeError(
            "LibreOffice is required but `soffice` was not found in PATH. "
            "Install LibreOffice in the runtime environment."
        )

    with tempfile.TemporaryDirectory(prefix="excel-recalc-") as tmp_dir:
        tmp_dir_path = Path(tmp_dir)
        staged = tmp_dir_path / input_path.name
        staged.write_bytes(input_path.read_bytes())

        cmd = [
            soffice,
            "--headless",
            "--nologo",
            "--nofirststartwizard",
            "--convert-to",
            "xlsx",
            "--outdir",
            str(tmp_dir_path),
            str(staged),
        ]
        completed = subprocess.run(cmd, capture_output=True, text=True)
        if completed.returncode != 0:
            raise RuntimeError(
                "LibreOffice recalculation failed. "
                f"stdout={completed.stdout.strip()} stderr={completed.stderr.strip()}"
            )

        converted = tmp_dir_path / (input_path.stem + ".xlsx")
        if not converted.exists():
            raise RuntimeError("LibreOffice did not produce an output workbook")

        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(converted.read_bytes())

    return output_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Recalculate workbook using LibreOffice")
    parser.add_argument("--input", required=True, help="Path to source workbook")
    parser.add_argument("--output", required=True, help="Path to recalculated workbook")
    args = parser.parse_args()

    in_path = Path(args.input)
    out_path = Path(args.output)

    if not in_path.exists():
        raise SystemExit(f"Input workbook not found: {in_path}")

    result = recalc(in_path, out_path)
    print(f"Saved recalculated workbook to {result}")


if __name__ == "__main__":
    main()
