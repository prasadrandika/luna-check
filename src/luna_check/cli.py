"""Command line entry point: luna-check [PATH] [options]."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__, rules
from .report import json_report, text_report
from .scanner import scan


def main(argv=None) -> int:
    p = argparse.ArgumentParser(
        prog="luna-check",
        description="Find code that breaks when GPT-4o, GPT-4o mini, GPT-4.1 and "
        "GPT-4.1 mini shut down in the OpenAI API on Jan 14, 2027.",
    )
    p.add_argument("path", nargs="?", default=".", help="folder or file to scan (default: .)")
    p.add_argument("--strict", action="store_true",
                   help="also report temperature/top_p/logprobs settings (not confirmed for gpt-6-luna)")
    p.add_argument("--include-tests", action="store_true", help="also scan test files")
    p.add_argument("--format", choices=("text", "json"), default="text")
    p.add_argument("--exit-zero", action="store_true", help="always exit 0, even with high findings")
    p.add_argument("--version", action="version", version=f"luna-check {__version__}")
    args = p.parse_args(argv)

    target = Path(args.path)
    if not target.exists():
        print(f"luna-check: no such file or folder: {args.path}", file=sys.stderr)
        return 2

    findings, count = scan(target, strict=args.strict, include_tests=args.include_tests)
    if args.format == "json":
        print(json_report(findings, count, args.path))
    else:
        print(text_report(findings, count, args.path, args.strict))

    if args.exit_zero:
        return 0
    return 1 if any(f.severity == rules.HIGH for f in findings) else 0


if __name__ == "__main__":
    sys.exit(main())
