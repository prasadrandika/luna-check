"""Text and JSON reports."""

from __future__ import annotations

import json
from itertools import groupby

from . import __version__, rules

FOOTER = "Need help migrating? github.com/prasadrandika"
LABEL = {rules.HIGH: "HIGH", rules.LOW: "LOW"}


def text_report(findings, files_scanned: int, target: str, strict: bool = False) -> str:
    out = [f"luna-check {__version__}: scanned {files_scanned} file(s) in {target}", ""]
    if not findings:
        out.append("No problems found for the Jan 14, 2027 shutdown of GPT-4o, GPT-4o mini, GPT-4.1 and GPT-4.1 mini.")
    for path, group in groupby(findings, key=lambda f: f.path):
        out.append(path)
        for f in group:
            if f.severity == rules.LOW:
                # Seed/demo files: one line each, so they don't bury the real problems.
                out.append(f"  line {f.line}  LOW  {f.rule.id}  {_short(f)}")
                continue
            out.append(f"  line {f.line}  {LABEL[f.severity]}  {f.rule.id}  {f.rule.title}")
            out.append(f"      {f.message}")
            out.append(f"      Fix: {f.fix}")
            out.append(f"      Source: {f.rule.source}")
        out.append("")
    low_rules = sorted({f.rule.id: f.rule for f in findings if f.severity == rules.LOW}.items())
    if low_rules:
        out.append("LOW = seed, demo, mock or sample file. Sources:")
        for rid, rule in low_rules:
            out.append(f"  {rid}  {rule.source}")
        out.append("")
    if findings:
        counts = {s: sum(1 for f in findings if f.severity == s) for s in LABEL}
        files = len({f.path for f in findings})
        out.append(f"Found {counts[rules.HIGH]} high, {counts[rules.LOW]} low in {files} file(s).")
    out.append("")
    out.append(FOOTER)
    return "\n".join(out)


def _short(f) -> str:
    if f.rule is rules.MODEL_ID:
        return f.message.split(" points to", 1)[0].split(" shuts down", 1)[0] + \
            f" shuts down on {rules.SHUTDOWN_DATE} -> {rules.REPLACEMENT}"
    return f.rule.title


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
