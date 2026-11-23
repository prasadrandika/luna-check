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
    "mistral": (
        "https://docs.mistral.ai/models.md",
        "https://docs.mistral.ai/models",
        "mistral.md",
    ),
    "deepseek": (
        "https://api-docs.deepseek.com/updates.md",
        "https://api-docs.deepseek.com/updates",
        "deepseek-updates.md",
    ),
    # xAI: the retirement guide holds the May 15, 2026 table, and the release
    # notes hold the later end-of-life and redirect notices.
    "xai": [
        (
            "https://docs.x.ai/developers/migration/may-15-retirement.md",
            "https://docs.x.ai/developers/migration/may-15-retirement",
            "xai-migration.md",
        ),
        (
            "https://docs.x.ai/developers/release-notes.md",
            "https://docs.x.ai/developers/release-notes",
            "xai-release.md",
        ),
    ],
    "cohere": (
        "https://docs.cohere.com/docs/deprecations.md",
        "https://docs.cohere.com/docs/deprecations",
        "cohere.md",
    ),
    "groq": (
        "https://console.groq.com/docs/deprecations.md",
        "https://console.groq.com/docs/deprecations",
        "groq.md",
    ),
}


def pages_of(platform: str) -> list:
    """[(fetch URL, cite URL, file name)] for a platform (most have one page)."""
    p = PAGES[platform]
    return p if isinstance(p, list) else [p]


# A parser that finds fewer rows than this has met a new page layout.
MIN_ENTRIES = {"openai": 60, "anthropic": 15, "gemini-api": 30, "vertex": 15, "azure": 5, "bedrock": 30,
               "mistral": 30, "deepseek": 4, "xai": 8, "cohere": 10, "groq": 25}

BACKTICK = re.compile(r"`([^`]+)`")
MONTHS = "January|February|March|April|May|June|July|August|September|October|November|December"
DATE_RE = re.compile(
    rf"\b((?:{MONTHS}|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)\.? \d{{1,2}}, \d{{4}}|\d{{4}}-\d{{2}}-\d{{2}})\b"
)


class LayoutError(Exception):
    pass


ORDINAL = re.compile(r"\b(\d{1,2})(?:st|nd|rd|th)\b")
US_DATE = re.compile(r"^\s*(\d{1,2})/(\d{1,2})/(\d{2})\s*$")


def parse_date(text: str):
    """The first date in text as YYYY-MM-DD, or None."""
    m = DATE_RE.search(ORDINAL.sub(r"\1", text or ""))
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
    return bool(re.fullmatch(r"[A-Za-z0-9][\w.:@/-]*", model_id))


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
                "behavior": "error",
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
        e.update({"behavior": "error", "source": url})
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
            "behavior": "redirect" if target else "error",
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
                "behavior": "error",
                "source": url,
            })
    return out


# --- Azure OpenAI -----------------------------------------------------------------

FOOTNOTE = re.compile(r"\^\d+\^")

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
            # Footnote markers such as "2027-01-14^2^" or "gpt-5.6-sol^4^" can sit in any cell.
            row = [FOOTNOTE.sub("", c).strip() for c in row]
            name, version, life, date = row[0], row[1], row[2].lower(), row[3]
            if life not in ("deprecated", "legacy", "retired"):
                continue
            date = parse_date(date)
            repl = row[4] if len(row) > 4 and row[4] not in ("—", "-", "") else None
            out.append({
                "platform": "azure",
                "ids": [f"{name}-{version}"],
                "aliases": [name],
                "version": version,
                "shutdown": date,
                "replacement": re.sub(r"\s*\(.*?\)", "", repl) if repl else None,
                "behavior": "error",
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
            "behavior": "error",
            "source": url,
        })
        out.append(e)
    return out


def _ids_in_list(text: str) -> list:
    """`a`, `b` and `c` -> [a, b, c]."""
    return BACKTICK.findall(text or "")


# --- Mistral AI -------------------------------------------------------------------

MD_LINK = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")


def parse_mistral(text: str, url: str, ov: dict) -> list:
    """The "Deprecated and retired models" table. Its Replacement cell links to a
    model page; the API name is the one the page's tables give for that link."""
    api_of = {}  # model page link -> API name
    rows_out = []
    for header, rows in md_tables(text):
        names = [h.lower() for h in header]
        if names[:3] != ["model", "api name", "status"]:
            continue
        col_ret = names.index("retirement") if "retirement" in names else None
        col_repl = names.index("replacement") if "replacement" in names else None
        for row in rows:
            link, api = MD_LINK.search(row[0]), BACKTICK.findall(row[1]) if len(row) > 1 else []
            if link and api:
                api_of.setdefault(link.group(2), api[0])
            if col_ret is not None:
                rows_out.append((row, col_ret, col_repl))
    entries = {}
    for row, col_ret, col_repl in rows_out:
        api = BACKTICK.findall(row[1])
        if not api or row[2].lower() not in ("deprecated", "retired") or len(row) <= col_ret:
            continue  # rows without an API name cannot be matched in code
        model, date = api[0], parse_date(row[col_ret])
        if not date or not keep_id(model, ov):
            continue
        repl = None
        if col_repl is not None and len(row) > col_repl:
            link = MD_LINK.search(row[col_repl])
            if link:
                repl = api_of.get(link.group(2))
                if repl is None:
                    raise LayoutError(f"mistral: no API name for the replacement {link.group(1)}")
        e = entries.get(model)
        if e:  # listed twice (Voxtral Mini, Mistral 7B)
            if e["shutdown"] != date:
                raise LayoutError(f"mistral: {model} has two dates, {e['shutdown']} and {date}")
            if repl and repl not in (e["replacement"] or "").split(" or "):
                e["replacement"] = " or ".join(x for x in (e["replacement"], repl) if x)
            continue
        entries[model] = {"platform": "mistral", "ids": [model], "shutdown": date, "replacement": repl,
                          # "A retired model no longer does [answer requests]."
                          "behavior": "error", "source": url}
    return list(entries.values())


# --- DeepSeek ---------------------------------------------------------------------

def parse_deepseek(text: str, url: str, ov: dict) -> list:
    """The change log: one "## Date: YYYY-MM-DD" section per update."""
    out = {}
    for sec in re.split(r"\n## Date: ", text)[1:]:
        day = sec[:10]
        # "The two legacy API model names, `a` and `b`, will be discontinued in three months (2026-07-24)."
        m = re.search(r"model names,?\s+((?:`[^`]+`(?:,\s*|\s+and\s+)?)+),?\s+will be discontinued[^(\n]*"
                      r"\((\d{4}-\d{2}-\d{2})\)", sec)
        if m:
            repl = re.search(r"should be set to ((?:`[^`]+`(?:\s+or\s+)?)+)", sec)
            for i in _ids_in_list(m.group(1)):
                out[i] = {"platform": "deepseek", "ids": [i], "shutdown": m.group(2),
                          "replacement": " or ".join(_ids_in_list(repl.group(1))) if repl else None,
                          "behavior": "error", "source": url}
        # "... have been retired; for compatibility, the model names `a` and `b` are temporarily routed to ..."
        m = re.search(r"model names?\s+((?:`[^`]+`(?:,\s*|\s+and\s+)?)+)\s+(?:is|are)\s+(?:temporarily\s+)?"
                      r"routed to", sec)
        target = re.search(r"[Cc]hange the model name to `([^`]+)`", sec)
        if m and target and "retired" in sec:
            for i in _ids_in_list(m.group(1)):
                out[i] = {"platform": "deepseek", "ids": [i], "shutdown": day,
                          "replacement": target.group(1), "behavior": "redirect",
                          "routes_to": target.group(1), "source": url}
    return list(out.values())


# --- xAI --------------------------------------------------------------------------

LONG_DATE = rf"(?:{MONTHS}) \d{{1,2}}, \d{{4}}"


def parse_xai(pages: list, ov: dict) -> list:
    """pages: [(retirement guide text, url), (release notes text, url)]."""
    (guide, guide_url), (notes, notes_url) = pages
    out = {}
    m = re.search(r"Effective (?:\*\*)?(" + LONG_DATE + ")", guide)
    if not m:
        raise LayoutError("xai: no 'Effective <date>' in the retirement guide")
    date = parse_date(m.group(1))
    for header, rows in md_tables(guide):
        if [h.lower() for h in header][:1] != ["model being retired"]:
            continue
        for row in rows:
            ids, target = BACKTICK.findall(row[0]), BACKTICK.findall(row[1]) if len(row) > 1 else []
            if not ids or not target:
                continue
            e = {"platform": "xai", "ids": [ids[0]], "shutdown": date, "replacement": target[0],
                 # "requests to the retired model slugs above will automatically redirect"
                 "behavior": "redirect", "routes_to": target[0], "source": guide_url}
            effort = re.search(r"with `(\w+)` reasoning effort", row[1])
            if effort:
                e["routes_effort"] = effort.group(1)
            out[ids[0]] = e

    def add(i, **kw):
        out[i] = dict({"platform": "xai", "ids": [i], "replacement": None, "source": notes_url}, **kw)

    for m in re.finditer(r"`([^`]+)` reached end of life on (" + LONG_DATE + r") and is no longer served", notes):
        add(m.group(1), shutdown=parse_date(m.group(2)), behavior="error")
    for m in re.finditer(r"On (" + LONG_DATE + r"), `([^`]+)` is retired\. Requests to the slug will be served "
                         r"by `([^`]+)`", notes):
        add(m.group(2), shutdown=parse_date(m.group(1)), replacement=m.group(3), behavior="redirect",
            routes_to=m.group(3))
    for m in re.finditer(r"`([^`]+)` is deprecated and reaches end of life on (" + LONG_DATE + r")\. All requests "
                         r"to that slug are routed to `([^`]+)`", notes):
        add(m.group(1), shutdown=parse_date(m.group(2)), replacement=m.group(3), behavior="redirect",
            routes_to=m.group(3))
    for m in re.finditer(r"`([^`]+)` is deprecated\. To upgrade, set `model` to ((?:`[^`]+`(?:\s+or\s+)?)+)", notes):
        add(m.group(1), shutdown=None, replacement=" or ".join(_ids_in_list(m.group(2))), behavior="error")
    # A later notice can change where a retired slug's requests go.
    for m in re.finditer(r"Requests to ((?:`[^`]+`(?:,\s*|\s+and\s+)?)+)\s+are now served by `([^`]+)`", notes):
        for i in _ids_in_list(m.group(1)):
            if i in out:
                out[i]["routes_to"] = m.group(2)
                out[i]["behavior"] = "redirect"
    return list(out.values())


# --- Cohere -------------------------------------------------------------------------

# A run of "* `model-id` ..." bullets; it ends at the first bullet without an ID.
BULLETS = r"((?:\n[ \t]*\*[ \t]+`[^\n]+)+)"


def parse_cohere(text: str, url: str, ov: dict) -> list:
    """The "Deprecation History" sections. "Requests to shutdown models and
    endpoints will fail." Deprecated models get a shutdown date later."""
    out = {}
    for sec in re.split(r"\n### ", text)[1:]:
        m = re.search(r"Effective ([^,\n]+, \d{4}), the following models will be retired:\s*?" + BULLETS, sec)
        if m:
            embed = re.search(r"Embedding tasks alternatives:\s*?" + BULLETS, sec)
            chat = re.search(r"Chat tasks alternatives:\s*?" + BULLETS, sec)
            for i in _ids_in_list(m.group(2)):
                alt = embed if i.startswith("embed-") else chat
                out[i] = {"platform": "cohere", "ids": [i], "shutdown": parse_date(m.group(1)),
                          "replacement": " or ".join(_ids_in_list(alt.group(1))) if alt else None,
                          "behavior": "error", "source": url}
        m = re.search(r"Deprecated Models:\s*?" + BULLETS, sec)
        if m:
            rec = re.search(r"we recommend you use ((?:`[^`]+`(?:,\s*or\s+|,\s*|\s+or\s+)?)+)", sec)
            for line in m.group(1).strip().split("\n"):
                ids = BACKTICK.findall(line)
                if not ids:
                    continue
                e = {"platform": "cohere", "ids": [ids[0]], "shutdown": None,
                     "replacement": " or ".join(_ids_in_list(rec.group(1)))
                     if rec and ids[0].startswith("command") else None,
                     "behavior": "error", "source": url}
                aliases = re.findall(r"alias `([^`]+)`", line)
                if aliases:
                    e["aliases"] = aliases
                out[ids[0]] = e
        for header, rows in md_tables(sec):
            names = [h.lower() for h in header]
            if names[:2] != ["shutdown date", "deprecated model"]:
                continue
            col_repl = next((k for k, h in enumerate(names) if "replacement" in h), None)
            for row in rows:
                ids, date = BACKTICK.findall(row[1]), parse_date(row[0])
                if ids and date:
                    out[ids[0]] = {"platform": "cohere", "ids": [ids[0]], "shutdown": date,
                                   "replacement": replacement_of(row[col_repl]) if col_repl is not None else None,
                                   "behavior": "error", "source": url}
    return list(out.values())


# --- Groq ---------------------------------------------------------------------------

def parse_groq(text: str, url: str, ov: dict) -> list:
    """One table per notice. "Requests to deprecated model IDs will return errors"."""
    out = {}
    for header, rows in md_tables(text):
        names = [h.lower() for h in header]
        if len(names) < 3 or names[1] != "shutdown date":
            continue
        for row in rows:
            if len(row) < 3:
                continue
            model = row[0].strip("` ")
            d = US_DATE.match(row[1])
            if not d or not keep_id(model, ov):
                continue
            date = f"20{d.group(3)}-{int(d.group(1)):02d}-{int(d.group(2)):02d}"
            # "a b (text-only workloads)" lists two models: "a or b".
            cell = re.sub(r"\s*\(.*?\)", "", row[2]).strip()
            repl = [x for x in re.split(r"\s+or\s+|\s+", cell) if x and x not in ("—", "-")]
            if model in out and out[model]["shutdown"] > date:
                continue  # listed twice: keep the later notice
            out[model] = {"platform": "groq", "ids": [model], "shutdown": date,
                          "replacement": " or ".join(repl) or None, "behavior": "error", "source": url}
    return list(out.values())


PARSERS = {
    "openai": parse_openai,
    "anthropic": parse_anthropic,
    "gemini-api": parse_gemini,
    "vertex": parse_vertex,
    "azure": parse_azure,
    "bedrock": parse_bedrock,
    "mistral": parse_mistral,
    "deepseek": parse_deepseek,
    "xai": parse_xai,  # two pages
    "cohere": parse_cohere,
    "groq": parse_groq,
}


def fetch(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "luna-check-models-builder"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.read().decode("utf-8", errors="replace")


def build(pages_dir=None, today=None) -> dict:
    today = today or dt.date.today().isoformat()
    ov = json.loads(OVERRIDES.read_text(encoding="utf-8"))
    models, sources = [], {}
    for platform in PAGES:
        pages = [((Path(pages_dir) / fname).read_text(encoding="utf-8") if pages_dir else fetch(fetch_url), cite)
                 for fetch_url, cite, fname in pages_of(platform)]
        cite_url = pages[0][1]
        if len(pages) == 1:
            found = PARSERS[platform](pages[0][0], cite_url, ov)
        else:
            found = PARSERS[platform](pages, ov)
        if len(found) < MIN_ENTRIES[platform]:
            raise LayoutError(f"{platform}: only {len(found)} entries (expected {MIN_ENTRIES[platform]}+); page layout changed?")
        for e in found:
            e["checked"] = today
            # Bedrock: retired only once the last region's EOL date has passed.
            last = e["regions"][-1]["date"] if e.get("regions") else e["shutdown"]
            e["status"] = "retired" if last and last < today else "deprecated"
        models.extend(found)
        sources[platform] = {"url": cite_url, "checked": today}
        if len(pages) > 1:
            sources[platform]["also"] = [cite for _, cite in pages[1:]]
    # behavior: what a request gets after the shutdown date, as the page says:
    # "error" (the request fails) or "redirect" (served by routes_to instead).
    order = ["platform", "ids", "aliases", "version", "status", "shutdown", "regions",
             "replacement", "behavior", "routes_to", "routes_effort", "source", "checked"]
    models = [{k: e[k] for k in order if k in e} for e in models]
    return {
        "schema": 1,
        "note": "Generated by scripts/build_models.py from the official pages in 'sources'. Do not edit by hand.",
        "sources": sources,
        # Also everyday words in code: LC001 reports these only as a model setting's value.
        "word_ids": ov.get("word_ids", []),
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
    with open(args.out, "w", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(data, indent=1, ensure_ascii=False) + "\n")
    counts = {}
    for e in data["models"]:
        counts[e["platform"]] = counts.get(e["platform"], 0) + 1
    print(f"wrote {args.out}: " + ", ".join(f"{k} {v}" for k, v in counts.items()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
