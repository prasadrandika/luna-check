"""LC001 for config files: .env, YAML, JSON and TOML.

Config files are not parsed. Each line is matched against simple key/value
shapes, and a retiring model ID is reported only when it is the value of a
model-like key such as model, model_name, default_model or OPENAI_MODEL.
"""

from __future__ import annotations

import bisect
import re
from pathlib import Path

from . import models, rules
from .checks import ANY_MODEL_RE, CATALOG_MIN, PRICE_RE, model_finding

ENV, YAML, JSON, TOML = "env", "yaml", "json", "toml"

CONFIG_EXTENSIONS = {".yaml": YAML, ".yml": YAML, ".json": JSON, ".toml": TOML, ".env": ENV}

# Lockfiles and package manifests: never app config.
SKIP_NAMES = {
    "package.json", "package-lock.json", "npm-shrinkwrap.json", "pnpm-lock.yaml",
    "yarn.lock", "bun.lock", "deno.lock", "composer.json", "composer.lock",
    "pipfile.lock", "poetry.lock", "uv.lock", "pyproject.toml", "cargo.toml",
    "cargo.lock", "go.sum", "pdm.lock", "bower.json", "gemfile.lock",
}
SKIP_NAME_RE = re.compile(r"(?i)([.-]lock\.(json|ya?ml|toml)$|\.lock$)")

# Example, sample and template configs are LOW (as are seed/demo/mock/fixture
# files, through the scanner's usual rule).
EXAMPLE_RE = re.compile(
    r"(?i)(^|[-_.])(example|examples|sample|samples|template|templates|tmpl|dist)([-_.]|$)"
)


# Folders of recorded API responses and snapshots: data, not config. (Code in
# them is still scanned as before; test folders are skipped as before.)
DATA_DIRS = {
    "testing", "__live__", "__snapshots__", "snapshots", "cassettes",
    "recordings", "__recordings__", "golden", "goldens",
}


def is_data_path(rel: Path) -> bool:
    return bool(DATA_DIRS & {p.lower() for p in rel.parts[:-1]})


def config_kind(name: str):
    """The config type of a file name, or None."""
    low = name.lower()
    if low in SKIP_NAMES or SKIP_NAME_RE.search(low):
        return None
    if low == ".env" or low.startswith(".env."):
        return ENV
    return CONFIG_EXTENSIONS.get(Path(low).suffix)


def is_example_config(rel: Path) -> bool:
    parts = list(rel.parts[:-1]) + [rel.name]
    return any(EXAMPLE_RE.search(p) for p in parts)


def is_model_key(key: str) -> bool:
    """model, models, model_name, model_id, default_model, OPENAI_MODEL, llmModel, ..."""
    key = key.strip().strip("\"'")
    key = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", key)  # camelCase -> snake_case
    key = re.sub(r"[-.\s]", "_", key).lower()
    return bool(re.search(r"(^|_)models?(_?name|_?id)?$", key))


_COMMENT = re.compile(r"\s+[#;].*$")
_ENV_LINE = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][\w.-]*)\s*=\s*(.*)$")
_YAML_LINE = re.compile(r"^(\s*)(?:-\s+)?([\"']?[\w.-]+[\"']?)\s*:(?:\s+(.*))?$")
_YAML_ITEM = re.compile(r"^(\s*)-\s+(.*)$")
_TOML_LINE = re.compile(r"^\s*([\"']?[\w.-]+[\"']?)\s*=\s*(.*)$")
_JSON_PAIR = re.compile(r'"((?:[^"\\]|\\.)*)"\s*:\s*("(?:[^"\\]|\\.)*"|\[[^\[\]{}]*\])')
_QUOTED = re.compile(r'"((?:[^"\\]|\\.)*)"|\'([^\']*)\'')


def _unquote(v: str) -> str:
    v = v.strip()
    if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
        return v[1:-1]
    return _COMMENT.sub("", v).strip()


def _inline_list(v: str):
    """Items of an inline list such as [a, "b", 'c'], or None if v is not one."""
    v = _COMMENT.sub("", v.strip()).strip()
    if not (v.startswith("[") and v.endswith("]")):
        return None
    return [_unquote(x) for x in v[1:-1].split(",") if x.strip()]


def _json_objects(text: str) -> list:
    """(open, close) offsets of every {...} object in a JSON text, sorted by open."""
    spans = []
    stack = []
    in_str = False
    i = 0
    while i < len(text):
        ch = text[i]
        if in_str:
            if ch == "\\":
                i += 1
            elif ch == '"':
                in_str = False
        elif ch == '"':
            in_str = True
        elif ch == "{":
            stack.append(i)
        elif ch == "}" and stack:
            spans.append((stack.pop(), i + 1))
        i += 1
    return sorted(spans)


def _enclosing(objects: list, opens: list, offset: int):
    """The innermost object that contains offset, or None."""
    k = bisect.bisect_right(opens, offset) - 1
    while k >= 0:
        a, b = objects[k]
        if b > offset:
            return a, b
        k -= 1
    return None


def _pairs(text: str, kind: str):
    """Yield (line, key, value, group) for every key/value shape in a config file.

    `group` is the same for every value of one list, so lists can be counted.
    """
    if kind == JSON:
        starts = [0] + [i + 1 for i, ch in enumerate(text) if ch == "\n"]
        objects = _json_objects(text)
        opens = [a for a, _ in objects]
        for m in _JSON_PAIR.finditer(text):
            obj = _enclosing(objects, opens, m.start())
            if obj and PRICE_RE.search(text[obj[0] : obj[1]]):
                continue  # a price or usage record (model, price, cost...), not a setting
            raw = m.group(2)
            if raw.startswith("["):
                for q in _QUOTED.finditer(raw):
                    off = m.start(2) + q.start()
                    yield bisect.bisect_right(starts, off), m.group(1), q.group(1) or "", m.start()
            else:
                yield bisect.bisect_right(starts, m.start(2)), m.group(1), raw[1:-1], m.start()
        return

    lines = text.split("\n")
    block = None  # (key, indent, group): a key whose value is a list on the lines below
    prev_name = None  # "name: X" followed by "value: ..." (Kubernetes env, for example)
    for n, line in enumerate(lines, 1):
        stripped = line.strip()
        if not stripped or stripped.startswith(("#", ";", "//")):
            continue
        if kind == ENV:
            m = _ENV_LINE.match(line)
            if m:
                yield n, m.group(1), _unquote(m.group(2)), n
            continue
        if kind == TOML:
            if block is not None:  # inside a multi-line array
                for q in _QUOTED.finditer(line):
                    yield n, block[0], q.group(1) or q.group(2), block[2]
                if "]" in _COMMENT.sub("", line):
                    block = None
                continue
            m = _TOML_LINE.match(line)
            if not m:
                continue
            key, v = m.group(1).strip("\"'"), m.group(2).strip()
            if v.startswith("[") and "]" not in _COMMENT.sub("", v):
                block = (key, 0, n)
                for q in _QUOTED.finditer(v):
                    yield n, key, q.group(1) or q.group(2), n
                continue
            items = _inline_list(v)
            for item in items if items is not None else [_unquote(v)]:
                yield n, key, item, n
            continue

        # YAML
        indent = len(line) - len(line.lstrip())
        item = _YAML_ITEM.match(line)
        if block is not None and (indent < block[1] or (indent == block[1] and not item)):
            block = None
        if item and not _YAML_LINE.match(line):
            value = item.group(2)
            env = _ENV_LINE.match(value)  # docker compose: - OPENAI_MODEL=gpt-4o
            if env:
                yield n, env.group(1), _unquote(env.group(2)), n
            elif block is not None:
                yield n, block[0], _unquote(value), block[2]
            continue
        m = _YAML_LINE.match(line)
        if not m:
            continue
        key, value = m.group(2).strip("\"'"), (m.group(3) or "").strip()
        if not value or value.startswith(("#", "|", ">")):
            block = (key, indent, n)
            continue
        if key == "name":
            prev_name = _unquote(value)
            continue
        if key == "value" and prev_name:
            yield n, prev_name, _unquote(value), n
            prev_name = None
            continue
        prev_name = None
        items = _inline_list(value)
        for it in items if items is not None else [_unquote(value)]:
            yield n, key, it, n


def check_config(text: str, path: str, kind: str) -> list:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = text.split("\n")
    context = models.platforms_in(text)
    pairs = [p for p in _pairs(text, kind) if is_model_key(p[1])]
    names = {}
    for _, _, value, group in pairs:
        if ANY_MODEL_RE.match(value):
            names.setdefault(group, set()).add(value)
    catalogs = {g for g, s in names.items() if len(s) >= CATALOG_MIN}
    out = []
    seen = set()
    for line, key, value, group in pairs:
        if not value or re.search(r"\s", value):
            continue
        if PRICE_RE.search(lines[line - 1] if 0 < line <= len(lines) else ""):
            continue
        for _, model in models.catalog().find(value):
            if (line, model) in seen:
                continue
            rep = models.describe(model, context)
            if rep is None:
                continue
            seen.add((line, model))
            f = model_finding(path, line, rep, group in catalogs)
            f.message += f' (Config key "{key}".)'
            if f.severity == rules.HIGH and rep.replacement and " or " not in rep.replacement:
                f.fix = f'Set {key} to "{rep.replacement}".'
            out.append(f)
    return out
