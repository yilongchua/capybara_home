from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from src.control_plane.prompt_tools import CIDMask, CSVInterpreter


def _print_json(payload: Any) -> None:
    sys.stdout.write(json.dumps(payload, indent=2, ensure_ascii=False))
    sys.stdout.write("\n")


def _mask_command(args: argparse.Namespace) -> int:
    masker = CIDMask()
    masked = masker.mask_text(args.text)
    if args.prompt:
        prompts = masker.render_prompt(input_text=args.text, replace_with=args.replace_with)
        _print_json({"masked_text": masked, "prompts": prompts})
        return 0
    if args.json:
        _print_json({"masked_text": masked})
        return 0
    sys.stdout.write(masked + "\n")
    return 0


def _csv_command(args: argparse.Namespace) -> int:
    interpreter = CSVInterpreter()
    brief = interpreter.interpret(args.source, max_rows=args.max_rows)
    if args.prompt:
        prompts = interpreter.render_prompt(
            brief=brief,
            domain_context=args.domain_context or "",
        )
        _print_json({"brief": brief, "prompts": prompts})
        return 0
    _print_json(brief)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="control-plane-cli",
        description="Local control-plane utilities (CID masking + CSV interpreter).",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    mask = subparsers.add_parser("mask", help="Mask sensitive data in a string.")
    mask.add_argument("text", help="Input text to mask.")
    mask.add_argument(
        "--replace-with",
        default="[REDACTED]",
        help="Replacement token for masked values.",
    )
    mask.add_argument("--json", action="store_true", help="Return JSON output.")
    mask.add_argument(
        "--prompt",
        action="store_true",
        help="Include rendered system/user prompts in the output JSON.",
    )
    mask.set_defaults(func=_mask_command)

    csv = subparsers.add_parser("csv", help="Interpret a CSV/Excel/Google Sheet.")
    csv.add_argument("source", help="Path or URL to the CSV/Excel/Google Sheet.")
    csv.add_argument(
        "--max-rows",
        type=int,
        default=10,
        help="Number of rows to include in preview (default: 10).",
    )
    csv.add_argument(
        "--domain-context",
        default="",
        help="Optional domain context for prompt rendering.",
    )
    csv.add_argument(
        "--prompt",
        action="store_true",
        help="Include rendered system/user prompts in the output JSON.",
    )
    csv.set_defaults(func=_csv_command)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
