"""Text and JSON reports."""

from __future__ import annotations

import json
from itertools import groupby

from . import __version__, rules

FOOTER = "Need help migrating? prasadrandika.github.io"
LABEL = {rules.HIGH: "HIGH", rules.LOW: "LOW"}


def text_report(findings, files_scanned: int, target: str, strict: bool = False) -> str:
    out = [f"luna-check {__version__}: scanned {files_scanned} file(s) in {target}", ""]
    if not findings:
        out.append("No retired or retiring models or endpoints found.")
    for path, group in groupby(findings, key=lambda f: f.path):
        out.append(path)
        for f in group:
            if f.severity == rules.LOW:
                # One line each, so they don't bury the real problems.
                why = f"  ({f.low_reason})" if f.low_reason else ""
                out.append(f"  line {f.line}  LOW  {f.rule.id}  {_short(f)}{why}")
                continue
            out.append(f"  line {f.line}  {LABEL[f.severity]}  {f.rule.id}  {f.rule.title}")
            out.append(f"      {f.message}")
            out.append(f"      Fix: {f.fix}")
            out.append(f"      Source: {f.source or f.rule.source}")
        out.append("")
    low_sources = sorted({(f.rule.id, f.source or f.rule.source) for f in findings if f.severity == rules.LOW})
    if low_sources:
        out.append("LOW = seed, demo, mock or sample file, example config, one entry in a list of")
        out.append("      many model names, or no shutdown date yet. Sources:")
        for rid, src in low_sources:
            out.append(f"  {rid}  {src}")
        out.append("")
    if findings:
        counts = {s: sum(1 for f in findings if f.severity == s) for s in LABEL}
        files = len({f.path for f in findings})
        out.append(f"Found {counts[rules.HIGH]} high, {counts[rules.LOW]} low in {files} file(s).")
    out.append("")
    out.append(FOOTER)
    return "\n".join(out)


def _short(f) -> str:
    return f.short or f.rule.title


def json_report(findings, files_scanned: int, target: str) -> str:
    return json.dumps(
        {
            "version": __version__,
            "target": target,
            "files_scanned": files_scanned,
            "findings": [f.to_dict() for f in findings],
            "footer": FOOTER,
        },
        indent=2,
    )
