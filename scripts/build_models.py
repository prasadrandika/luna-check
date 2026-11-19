"""Build src/luna_check/data/models.json from the providers' official pages.

    python scripts/build_models.py                 # fetch the pages
    python scripts/build_models.py --pages DIR     # read saved copies instead

Only the standard library is used. Each parser reads one official page and
keeps only what the page states: model IDs, shutdown dates and the listed
replacement. scripts/models_overrides.json adds the few facts that are not in
one table row (see the notes in that file).

The parsers fail loudly when a page's layout changes (too few rows), so a
layout change is never mistaken for "every model was un-deprecated".
"""

from __future__ import annotations

import argparse
import datetime as dt
import html
import json
import re
import sys
import urllib.request
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "src" / "luna_check" / "data" / "models.json"
OVERRIDES = Path(__file__).resolve().parent / "models_overrides.json"

# platform -> (URL to fetch, URL to cite, saved file name)
PAGES = {
    "openai": (
        "https://developers.openai.com/api/docs/deprecations.md",
        "https://developers.openai.com/api/docs/deprecations",
        "openai.md",
    ),
    "anthropic": (
        "https://platform.claude.com/docs/en/about-claude/model-deprecations.md",
        "https://platform.claude.com/docs/en/about-claude/model-deprecations",
        "anthropic.md",
    ),
    "gemini-api": (
        "https://ai.google.dev/gemini-api/docs/deprecations.md.txt",
        "https://ai.google.dev/gemini-api/docs/deprecations",
        "gemini.md",
    ),
    "vertex": (
        "https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/model-versions",
        "https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/model-versions",
        "vertex-versions.html",
    ),
    "azure": (
        "https://learn.microsoft.com/en-us/azure/foundry/openai/concepts/model-retirement-schedule?accept=text/markdown",
        "https://learn.microsoft.com/en-us/azure/foundry/openai/concepts/model-retirement-schedule",
        "azure.md",
    ),
    "bedrock": (
        "https://docs.aws.amazon.com/bedrock/latest/userguide/model-lifecycle-legacy.md",
        "https://docs.aws.amazon.com/bedrock/latest/userguide/model-lifecycle-legacy.html",
        "bedrock.md",
    ),
}

# A parser that finds fewer rows than this has met a new page layout.
MIN_ENTRIES = {"openai": 60, "anthropic": 15, "gemini-api": 30, "vertex": 15, "azure": 5, "bedrock": 30}

BACKTICK = re.compile(r"`([^`]+)`")
MONTHS = "January|February|March|April|May|June|July|August|September|October|November|December"
DATE_RE = re.compile(
    rf"\b((?:{MONTHS}|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)\.? \d{{1,2}}, \d{{4}}|\d{{4}}-\d{{2}}-\d{{2}})\b"
)


class LayoutError(Exception):
    pass


def parse_date(text: str):
    """The first date in text as YYYY-MM-DD, or None."""
    m = DATE_RE.search(text or "")
    if not m:
        return None
    s = m.group(1).replace("Sept ", "Sep ").replace(".", "")
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
        return s
    for fmt in ("%B %d, %Y", "%b %d, %Y"):
        try:
            return dt.datetime.strptime(s, fmt).date().isoformat()
        except ValueError:
            pass
    return None


def is_exact_date(text: str) -> bool:
    """A real shutdown date, not 'X or later', 'Not before X', 'To be announced'."""
    t = (text or "").lower()
    if any(w in t for w in ("or later", "not before", "no sooner", "not sooner", "to be announced", "no ")):
        return False
    return parse_date(text) is not None


def md_tables(text: str):
    """Yield (header cells, [row cells]) for each pipe table in markdown text."""
    lines = text.split("\n")
    i = 0
    while i < len(lines):
        if lines[i].lstrip().startswith("|") and i + 1 < len(lines) and re.match(r"^\s*\|[\s:|-]+\|?\s*$", lines[i + 1]):
            header = _cells(lines[i])
            rows = []
            i += 2
            while i < len(lines) and lines[i].lstrip().startswith("|"):
                rows.append(_cells(lines[i]))
                i += 1
            yield header, rows
        else:
            i += 1


def _cells(line: str) -> list:
    parts = line.strip().strip("|").split("|")
    return [p.strip() for p in parts]


def replacement_of(text: str):
    """Model IDs named in a replacement cell, joined with ' or '."""
    ids = [t for t in BACKTICK.findall(text or "") if not t.startswith(("/", "reasoning", "service_tier"))]
    return " or ".join(dict.fromkeys(ids)) or None


def keep_id(model_id: str, overrides: dict) -> bool:
    if model_id in overrides.get("exclude_ids", []):
        return False
    return bool(re.fullmatch(r"[A-Za-z0-9][\w.:@-]*", model_id))


# --- OpenAI -------------------------------------------------------------------

def parse_openai(text: str, url: str, ov: dict) -> list:
    out = []
    for header, rows in md_tables(text):
        names = [h.lower() for h in header]
        if not names or "shutdown date" not in names[0]:
            continue
        col_model = next((k for k, h in enumerate(names) if h.startswith("affected model")), None)
        col_repl = next((k for k, h in enumerate(names) if "replacement" in h), None)
        if col_model is None:
            continue  # the feature/endpoint table: see the LC006 rule instead
        for row in rows:
            if len(row) <= max(col_model, col_repl or 0):
                continue
            date = parse_date(row[0])
            affected = row[col_model]
            if not date or affected.lower().startswith(("new fine-tuning", "fine-tuning on")):
                continue
            ids = [t for t in BACKTICK.findall(affected) if keep_id(t, ov) and not t.startswith("/")]
            ids = [t for t in ids if ":" not in t and "=" not in t]
            if not ids:
                continue
            entry = {
                "platform": "openai",
                "ids": ids,
                "shutdown": date,
                "replacement": replacement_of(row[col_repl]) if col_repl is not None else None,
                "after_shutdown": "error",
                "source": url,
            }
            aliases = sorted({a for i in ids for a in ov.get("aliases", {}).get("openai", {}).get(i, [])})
            if aliases:
                entry["aliases"] = aliases
            out.append(entry)
    return out


# --- Anthropic ----------------------------------------------------------------

def parse_anthropic(text: str, url: str, ov: dict) -> list:
    entries = {}  # id -> entry

    # Deprecation history: one section per notice, with a table and maybe an alias sentence.
    sections = re.split(r"\n### ", text)
    for sec in sections:
        aliases = re.findall(r"includes `([^`]+)`, the same model.{1,3}s ID without a date", sec)
        for header, rows in md_tables(sec):
            names = [h.lower() for h in header]
            if names[:2] != ["retirement date", "deprecated model"]:
                continue
            for row in rows:
                date = parse_date(row[0])
                ids = BACKTICK.findall(row[1])
                if not date or not ids:
                    continue
                for i in ids:
                    e = entries.setdefault(i, {"platform": "anthropic", "ids": [i]})
                    e["shutdown"] = date
                    e["replacement"] = replacement_of(row[2])
                    if aliases:
                        e["aliases"] = sorted(set(e.get("aliases", [])) | set(aliases))

    # Model status table: deprecated models without a date yet, and date cross-checks.
    for header, rows in md_tables(text):
        names = [h.lower() for h in header]
        if not names or names[0] != "api model name":
            continue
        for row in rows:
            model, state, retire = row[0], row[1].lower(), row[3]
            if state not in ("deprecated", "retired"):
                continue
            e = entries.setdefault(model, {"platform": "anthropic", "ids": [model], "replacement": None})
            date = parse_date(retire) if is_exact_date(retire) else None
            if date and e.get("shutdown") and e["shutdown"] != date:
                raise LayoutError(f"anthropic: {model} has two dates, {e['shutdown']} and {date}")
            e["shutdown"] = e.get("shutdown") or date
    out = []
    for e in entries.values():
        e.setdefault("shutdown", None)
        e.update({"after_shutdown": "error", "source": url})
        out.append(e)
    return out


# --- Gemini API -----------------------------------------------------------------

def gemini_tables(text: str):
    """Yield row cell lists from the {% table %} blocks."""
    for block in re.findall(r"\{% table %\}(.*?)\{% /table %\}", text, re.S):
        rows = [r for r in re.split(r"\n\s*---\s*\n", block)]
        for raw in rows[1:]:  # rows[0] is the header
            cells = re.findall(r"^\s*\*[ \t]?(.*)$", raw, re.M)
            if cells:
                yield [c.strip() for c in cells]


def parse_gemini(text: str, url: str, ov: dict) -> list:
    routes = dict(re.findall(r"requests to\s+`([^`]+)`\s+will\s+automatically\s+route\s+to\s+\[?`([^`]+)`", text, re.S))
    out = []
    seen = set()
    for cells in gemini_tables(text):
        if len(cells) < 3:
            continue
        ids = BACKTICK.findall(cells[0])
        if not ids or not is_exact_date(cells[2]):
            continue
        model = ids[0]
        if model in seen:
            continue  # listed in two sections (Live models)
        seen.add(model)
        repl_cell = cells[3] if len(cells) > 3 else ""
        cell_route = re.search(r"route to\s+`([^`]+)`", repl_cell)
        target = routes.get(model) or (cell_route.group(1) if cell_route else None)
        entry = {
            "platform": "gemini-api",
            "ids": [model],
            "shutdown": parse_date(cells[2]),
            "replacement": BACKTICK.findall(repl_cell)[0] if BACKTICK.findall(repl_cell) else None,
            "after_shutdown": "routes" if target else "error",
            "source": url,
        }
        if target:
            entry["routes_to"] = target
        out.append(entry)
    return out


# --- Vertex AI (Gemini Enterprise Agent Platform) ----------------------------------

class _Tables(HTMLParser):
    """Collect every <table> as rows of (text, [code texts]) cells."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tables, self._rows, self._cell, self._codes = [], None, None, None
        self._in_code = 0

    def handle_starttag(self, tag, attrs):
        if tag == "table":
            self._rows = []
        elif tag == "tr" and self._rows is not None:
            self._rows.append([])
        elif tag in ("td", "th") and self._rows is not None:
            self._cell, self._codes = [], []
        elif tag == "code" and self._cell is not None:
            self._in_code += 1
            self._codes.append("")

    def handle_endtag(self, tag):
        if tag == "code" and self._in_code:
            self._in_code -= 1
        elif tag in ("td", "th") and self._cell is not None and self._rows:
            text = re.sub(r"\s+", " ", "".join(self._cell)).strip()
            self._rows[-1].append((text, [c.strip() for c in self._codes if c.strip()]))
            self._cell = None
        elif tag == "table" and self._rows is not None:
            self.tables.append(self._rows)
            self._rows = None

    def handle_data(self, data):
        if self._cell is not None:
            self._cell.append(data)
            if self._in_code:
                self._codes[-1] += data


def parse_vertex(text: str, url: str, ov: dict) -> list:
    p = _Tables()
    p.feed(text)
    out = []
    seen = set()
    for table in p.tables:
        if not table:
            continue
        header = [c[0].lower() for c in table[0]]
        if not header or "model id" not in header[0]:
            continue
        col_date = next((k for k, h in enumerate(header) if "retirement" in h), None)
        col_repl = next((k for k, h in enumerate(header) if "replacement" in h or "upgrade" in h), None)
        if col_date is None:
            continue
        for row in table[1:]:
            if len(row) <= col_date:
                continue
            ids = row[0][1] or [row[0][0]]
            date_text = row[col_date][0]
            if not ids or not is_exact_date(date_text):
                continue
            model = ids[0].rstrip("*")  # footnote markers
            if model in seen:
                continue
            seen.add(model)
            repl = row[col_repl][1] if col_repl is not None and col_repl < len(row) else []
            out.append({
                "platform": "vertex",
                "ids": [model],
                "shutdown": parse_date(date_text),
                "replacement": " or ".join(repl) or None,
                "after_shutdown": "error",
                "source": url,
            })
    return out


# --- Azure OpenAI -----------------------------------------------------------------

def parse_azure(text: str, url: str, ov: dict) -> list:
    m = re.search(r"\n### Azure OpenAI\s*\n(.*?)(?=\n#{2,3} )", text, re.S)
    if not m:
        raise LayoutError("azure: no 'Azure OpenAI' section")
    out = []
    for header, rows in md_tables(m.group(1)):
        names = [h.lower() for h in header]
        if names[:4] != ["model", "version", "lifecycle", "retirement date"]:
            continue
        for row in rows:
            name, version, life, date = row[0], row[1], row[2].lower(), row[3]
            if life not in ("deprecated", "legacy", "retired"):
                continue
            date = parse_date(re.sub(r"\^\d+\^", "", date))
            repl = row[4] if len(row) > 4 and row[4] not in ("—", "-", "") else None
            out.append({
                "platform": "azure",
                "ids": [f"{name}-{version}"],
                "aliases": [name],
                "version": version,
                "shutdown": date,
                "replacement": re.sub(r"\s*\(.*?\)", "", repl) if repl else None,
                "after_shutdown": "error",
                "source": url,
            })
    return out


# --- Amazon Bedrock ---------------------------------------------------------------

def parse_bedrock(text: str, url: str, ov: dict) -> list:
    start = text.find("**Models with a scheduled EOL date**")
    if start == -1:
        raise LayoutError("bedrock: no scheduled-EOL list")
    body = text[start:]
    entries = {}
    for block in re.split(r"\n(?=- \*\*)", body):
        mid = re.search(r"\*\*Model ID:\*\*\s*(.+)", block)
        if not mid:
            continue
        ids = [re.sub(r"\s*\(.*?\)", "", x).strip() for x in mid.group(1).split(",")]
        ids = [i for i in ids if i]
        groups = []
        for reg in re.finditer(r"\*\*Regions:\*\*\s*([^\n/]+?)(?:\s*/|\n|$)(.*?)(?=\n\s*- \*\*Regions:|\Z)", block, re.S):
            regions = [r.strip() for r in reg.group(1).split(",") if r.strip()]
            eol = re.search(r"\*\*EOL date:\*\*\s*([^\n/]+)", reg.group(0))
            if regions and eol and parse_date(eol.group(1)):
                groups.append({"regions": regions, "date": parse_date(eol.group(1))})
        if not groups:
            continue
        key = tuple(ids)
        e = entries.setdefault(key, {"platform": "bedrock", "ids": ids, "regions": []})
        for g in groups:
            if g not in e["regions"]:
                e["regions"].append(g)
    out = []
    for e in entries.values():
        e["regions"].sort(key=lambda g: g["date"])
        e.update({
            "shutdown": e["regions"][0]["date"],
            "replacement": None,  # the Bedrock page names none
            "after_shutdown": "error",
            "source": url,
        })
        out.append(e)
    return out


PARSERS = {
    "openai": parse_openai,
    "anthropic": parse_anthropic,
    "gemini-api": parse_gemini,
    "vertex": parse_vertex,
    "azure": parse_azure,
    "bedrock": parse_bedrock,
}


def fetch(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "luna-check-models-builder"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.read().decode("utf-8", errors="replace")


def build(pages_dir=None, today=None) -> dict:
    today = today or dt.date.today().isoformat()
    ov = json.loads(OVERRIDES.read_text(encoding="utf-8"))
    models, sources = [], {}
    for platform, (fetch_url, cite_url, fname) in PAGES.items():
        text = (Path(pages_dir) / fname).read_text(encoding="utf-8") if pages_dir else fetch(fetch_url)
        found = PARSERS[platform](text, cite_url, ov)
        if len(found) < MIN_ENTRIES[platform]:
            raise LayoutError(f"{platform}: only {len(found)} entries (expected {MIN_ENTRIES[platform]}+); page layout changed?")
        for e in found:
            e["checked"] = today
            # Bedrock: retired only once the last region's EOL date has passed.
            last = e["regions"][-1]["date"] if e.get("regions") else e["shutdown"]
            e["status"] = "retired" if last and last < today else "deprecated"
        models.extend(found)
        sources[platform] = {"url": cite_url, "checked": today}
    order = ["platform", "ids", "aliases", "version", "status", "shutdown", "regions",
             "replacement", "after_shutdown", "routes_to", "source", "checked"]
    models = [{k: e[k] for k in order if k in e} for e in models]
    return {
        "schema": 1,
        "note": "Generated by scripts/build_models.py from the official pages in 'sources'. Do not edit by hand.",
        "sources": sources,
        "models": models,
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pages", help="folder with saved copies of the pages")
    ap.add_argument("--today", help="date to record as 'checked' (YYYY-MM-DD)")
    ap.add_argument("--out", default=str(OUT))
    args = ap.parse_args(argv)
    try:
        data = build(args.pages, args.today)
    except LayoutError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    counts = {}
    for e in data["models"]:
        counts[e["platform"]] = counts.get(e["platform"], 0) + 1
    print(f"wrote {args.out}: " + ", ".join(f"{k} {v}" for k, v in counts.items()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
