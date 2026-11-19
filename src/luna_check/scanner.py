"""Walk a project, pick the files to scan and run the checks."""

from __future__ import annotations

import os
import re
from pathlib import Path

from . import rules
from .checks import run_all
from .config import check_config, config_kind, is_data_path, is_example_config
from .lexer import EXTENSIONS, lex

SKIP_DIRS = {
    ".git", ".hg", ".svn", "node_modules", "vendor", "third_party", "venv", ".venv",
    "env", ".env", ".tox", ".nox", "__pycache__", "site-packages", "dist", "build",
    ".next", ".nuxt", "coverage", ".mypy_cache", ".pytest_cache",
}
TEST_DIRS = {"test", "tests", "__tests__", "testdata", "spec", "specs", "e2e"}
TEST_FILE = re.compile(
    r"(^test_.*\.py$|^conftest\.py$|_test\.(py|go)$|\.(test|spec)\.[cm]?[jt]sx?$|\.d\.ts$)"
)
LOW_PART = re.compile(
    r"(?i)(^|[-_.])(seed|seeds|seeding|seeder|demo|demos|mock|mocks|fixture|fixtures|sample|samples)([-_.]|$)"
)
MAX_BYTES = 2_000_000
IGNORE_MARK = "luna-check: ignore"  # put this in a comment on a line to silence it


def is_test_path(rel: Path) -> bool:
    return bool(TEST_DIRS & {p.lower() for p in rel.parts[:-1]}) or bool(TEST_FILE.search(rel.name))


def is_low_path(rel: Path) -> bool:
    parts = list(rel.parts[:-1]) + [rel.stem]
    return any(LOW_PART.search(p) for p in parts)


def iter_files(root: Path, include_tests: bool):
    if root.is_file():
        yield root, Path(root.name)
        return
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS)
        rel_dir = Path(dirpath).relative_to(root)
        if not include_tests and TEST_DIRS & {p.lower() for p in rel_dir.parts}:
            dirnames[:] = []
            continue
        for name in sorted(filenames):
            path = Path(dirpath) / name
            rel = rel_dir / name
            if path.suffix.lower() not in EXTENSIONS:
                if config_kind(name) is None or is_data_path(rel):
                    continue
            if not include_tests and is_test_path(rel):
                continue
            yield path, rel


def _lower(found: list, reason: str, note: str) -> None:
    for f in found:
        if f.severity == rules.HIGH:
            f.severity = rules.LOW
            f.low_reason = reason
            f.message += note


def scan(root, strict: bool = False, include_tests: bool = False):
    """Return (findings, number_of_files_scanned)."""
    root = Path(root)
    findings = []
    count = 0
    for path, rel in iter_files(root, include_tests):
        try:
            if path.stat().st_size > MAX_BYTES:
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        kind = config_kind(path.name)
        if kind is None and path.suffix.lower() not in EXTENSIONS:
            continue  # a single file of a type luna-check does not read
        count += 1
        if kind is not None:
            lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
            found = [
                f for f in check_config(text, rel.as_posix(), kind)
                if IGNORE_MARK not in lines[f.line - 1]
            ]
            if is_example_config(rel):
                _lower(found, "example config", " (Example config, so lower priority.)")
        else:
            lx = lex(text, EXTENSIONS[path.suffix.lower()])
            found = [
                f for f in run_all(lx, rel.as_posix(), strict)
                if IGNORE_MARK not in lx.line_text(f.line)
            ]
        if is_low_path(rel):
            _lower(found, "seed/demo file", " (Seed/demo file, so lower priority.)")
        findings.extend(found)
    findings.sort(key=lambda f: (f.path, f.line, f.rule.id))
    return findings, count
