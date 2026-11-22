"""Weekly refresh of src/luna_check/data/models.json.

    python scripts/refresh_models.py [--pages DIR] [--today YYYY-MM-DD] [--out-dir DIR]

Builds fresh data from the official pages (scripts/build_models.py), compares
it with the committed models.json and decides:

  unchanged  nothing to do (only "checked" dates would differ)
  changed    models.json is rewritten and <out-dir>/pr-body.md lists every
             added, changed and removed entry with its source link
  layout     a page could not be read the way the parser expects: an error,
             0 rows, or far fewer rows than the committed data has.
             models.json is left alone and <out-dir>/issue-body.md says why.

The result is printed and, inside GitHub Actions, written to $GITHUB_OUTPUT
as `result=...`.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_models  # noqa: E402

# A platform whose row count falls below this share of the committed count is
# treated as a page layout change, not as models being un-deprecated.
MIN_SHARE = 0.5
IGNORED = ("checked",)  # differs on every run, so it is not a change by itself


def entry_key(e: dict) -> tuple:
    return (e["platform"], tuple(e["ids"]))


def comparable(e: dict) -> dict:
    return {k: v for k, v in e.items() if k not in IGNORED}


def diff(old: dict, new: dict) -> dict:
    """{'added': [...], 'removed': [...], 'changed': [(old, new, [fields])]}"""
    before = {entry_key(e): e for e in old["models"]}
    after = {entry_key(e): e for e in new["models"]}
    out = {"added": [], "removed": [], "changed": []}
    for k, e in after.items():
        if k not in before:
            out["added"].append(e)
        elif comparable(before[k]) != comparable(e):
            a, b = comparable(before[k]), comparable(e)
            fields = sorted(f for f in set(a) | set(b) if a.get(f) != b.get(f))
            out["changed"].append((before[k], e, fields))
    for k, e in before.items():
        if k not in after:
            out["removed"].append(e)
    return out


def counts(data: dict) -> dict:
    c = {}
    for e in data["models"]:
        c[e["platform"]] = c.get(e["platform"], 0) + 1
    return c


def layout_problems(old: dict, new: dict) -> list:
    """Platforms whose row count dropped to 0 or below MIN_SHARE of before."""
    problems = []
    oc, nc = counts(old), counts(new)
    for platform, n_old in sorted(oc.items()):
        n_new = nc.get(platform, 0)
        if n_new == 0 or n_new < n_old * MIN_SHARE:
            problems.append(f"`{platform}`: {n_new} rows now, {n_old} in the committed data")
    return problems


def _ids(e: dict) -> str:
    ids = ", ".join(f"`{i}`" for i in e["ids"])
    if e.get("version"):
        ids += f" (version {e['version']})"
    return ids


def _val(v) -> str:
    if v is None:
        return "none"
    if isinstance(v, list):
        if v and isinstance(v[0], dict):  # Bedrock region groups
            return "; ".join(f"{g['date']} ({len(g['regions'])} regions)" for g in v)
        return ", ".join(str(x) for x in v)
    return str(v)


def _src(e: dict) -> str:
    return f"[source]({e['source']})"


def pr_body(d: dict, new: dict, today: str) -> str:
    lines = [
        f"Weekly refresh of `src/luna_check/data/models.json` from the official deprecation pages, run on {today}.",
        "",
        f"**{len(d['added'])} added, {len(d['changed'])} changed, {len(d['removed'])} removed.** "
        "Each row links the page it comes from. Please check the rows against the pages before merging.",
        "",
    ]
    if d["added"]:
        lines += ["### Added", "", "| Platform | Model IDs | Shutdown | Replacement | Source |", "|---|---|---|---|---|"]
        for e in sorted(d["added"], key=entry_key):
            lines.append(f"| {e['platform']} | {_ids(e)} | {_val(e.get('shutdown'))} | "
                         f"{_val(e.get('replacement'))} | {_src(e)} |")
        lines.append("")
    if d["changed"]:
        lines += ["### Changed", "", "| Platform | Model IDs | Field | Before | After | Source |",
                  "|---|---|---|---|---|---|"]
        for old_e, new_e, fields in sorted(d["changed"], key=lambda t: entry_key(t[1])):
            for f in fields:
                lines.append(f"| {new_e['platform']} | {_ids(new_e)} | `{f}` | {_val(old_e.get(f))} | "
                             f"{_val(new_e.get(f))} | {_src(new_e)} |")
        lines.append("")
    if d["removed"]:
        lines += [
            "### Removed",
            "",
            "These are no longer on the pages. A page sometimes drops old rows; check that the model was not "
            "just moved to another section before merging.",
            "",
            "| Platform | Model IDs | Shutdown | Source |", "|---|---|---|---|",
        ]
        for e in sorted(d["removed"], key=entry_key):
            lines.append(f"| {e['platform']} | {_ids(e)} | {_val(e.get('shutdown'))} | {_src(e)} |")
        lines.append("")
    c = counts(new)
    lines += [
        "### Rows per platform",
        "",
        ", ".join(f"{p} {n}" for p, n in sorted(c.items())),
        "",
        "After merging: release a patch version so `pip install ...@vX` gets the new data, and run "
        "`python scripts/export_js_models.py <website>/js/luna-models.js` for the website.",
        "",
        "_Opened by the `refresh-models` workflow (scripts/refresh_models.py)._",
    ]
    return "\n".join(lines) + "\n"


def issue_body(problems: list, today: str) -> str:
    lines = [
        f"The weekly refresh on {today} could not read one or more official pages the way "
        "`scripts/build_models.py` expects, so it did **not** open a pull request and left `models.json` alone.",
        "",
        "Problems:",
        "",
    ]
    lines += [f"- {p}" for p in problems]
    lines += [
        "",
        "A page's layout probably changed. Update the parser in `scripts/build_models.py` (and its test in "
        "`tests/test_build_models.py`), then run the workflow again.",
        "",
        "Pages:",
        "",
    ]
    lines += [f"- {platform}: {cite}" for platform, (_, cite, _) in build_models.PAGES.items()]
    lines += ["", "_Opened by the `refresh-models` workflow (scripts/refresh_models.py)._"]
    return "\n".join(lines) + "\n"


def run(pages_dir=None, today=None, out_dir=".", data_path=build_models.OUT) -> str:
    today = today or dt.date.today().isoformat()
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    old = json.loads(Path(data_path).read_text(encoding="utf-8"))
    try:
        new = build_models.build(pages_dir, today)
        problems = layout_problems(old, new)
    except build_models.LayoutError as e:
        problems = [str(e)]
    except OSError as e:  # a page could not be fetched at all
        problems = [f"could not fetch a page: {e}"]
    if problems:
        (out_dir / "issue-body.md").write_text(issue_body(problems, today), encoding="utf-8")
        return "layout"
    d = diff(old, new)
    if not (d["added"] or d["changed"] or d["removed"]):
        return "unchanged"
    with open(data_path, "w", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(new, indent=1, ensure_ascii=False) + "\n")
    (out_dir / "pr-body.md").write_text(pr_body(d, new, today), encoding="utf-8")
    return "changed"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pages", help="folder with saved copies of the pages (default: fetch them)")
    ap.add_argument("--today", help="date to record as 'checked' (YYYY-MM-DD)")
    ap.add_argument("--out-dir", default=".", help="where to write pr-body.md / issue-body.md")
    args = ap.parse_args(argv)
    result = run(args.pages, args.today, args.out_dir)
    print(f"result={result}")
    gh_out = os.environ.get("GITHUB_OUTPUT")
    if gh_out:
        with open(gh_out, "a", encoding="utf-8") as f:
            f.write(f"result={result}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
