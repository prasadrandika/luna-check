"""The parsers in scripts/build_models.py, on small snippets in each page's format.

The snippets imitate the page layouts (table shapes and markup), with made-up
rows, so a layout change on a page shows up as a parser test to update.
"""

import importlib.util
import json
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    "build_models", Path(__file__).resolve().parent.parent / "scripts" / "build_models.py"
)
bm = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(bm)

OV = {"aliases": {"openai": {"m-2025-01-01": ["m"]}}, "exclude_ids": ["ada"]}


def test_openai_tables():
    text = """
| Shutdown date    | Affected model         | Status     | Recommended replacement | Notice date  |
| ---------------- | ---------------------- | ---------- | ----------------------- | ------------ |
| **Jan 14, 2027** | M (`m-2025-01-01`)     | Deprecated | `new-m`                 | Oct 14, 2026 |

| Shutdown date | Affected feature or endpoint | Status | Recommended replacement |
| ------------- | ---------------------------- | ------ | ----------------------- |
| **Nov 30, 2026** | `/v1/prompts` | Deprecated | text |

| Shutdown date | Affected model or feature | Listed replacement | Notice date |
| ------------- | ------------------------- | ------------------ | ----------- |
| **Jun 13, 2024** Earliest estimate | `old-1` Historical price $1 | `new-m` or `newer` | Jun 13, 2023 |
| **Jan 4, 2024** | `ada` Historical price | `x` | |
| **Oct 28, 2024** | New fine-tuning training on `babbage-002` | `x` | |
| **Jan 4, 2024** | `/v1/edits` | `x` | |
"""
    out = bm.parse_openai(text, "U", OV)
    assert [(e["ids"], e["shutdown"], e["replacement"], e.get("aliases")) for e in out] == [
        (["m-2025-01-01"], "2027-01-14", "new-m", ["m"]),
        (["old-1"], "2024-06-13", "new-m or newer", None),
    ]


def test_anthropic_status_and_history():
    text = """
## Model status

| API model name | Current state | Deprecated | Tentative retirement date |
| :------------- | :------------ | :--------- | :------------------------ |
| claude-new     | Active        | N/A        | Not sooner than June 9, 2027 |
| claude-x-1     | Deprecated    | June 9, 2026 | To be announced |
| claude-y-2     | Deprecated    | Sep 30, 2026 | November 30, 2026 |

### 2026-09-30: Claude Y

| Retirement date   | Deprecated model | Recommended replacement |
| ----------------- | ---------------- | ----------------------- |
| November 30, 2026 | `claude-y-2`     | `claude-new`            |

This retirement includes `claude-y`, the same model’s ID without a date.
"""
    out = {e["ids"][0]: e for e in bm.parse_anthropic(text, "U", OV)}
    assert set(out) == {"claude-x-1", "claude-y-2"}
    assert out["claude-y-2"]["shutdown"] == "2026-11-30"
    assert out["claude-y-2"]["aliases"] == ["claude-y"]
    assert out["claude-y-2"]["replacement"] == "claude-new"
    assert out["claude-x-1"]["shutdown"] is None


def test_anthropic_conflicting_dates_fail_loudly():
    text = """
| API model name | Current state | Deprecated | Tentative retirement date |
| :- | :- | :- | :- |
| claude-y-2 | Deprecated | x | December 1, 2026 |

### 2026-09-30: Claude Y

| Retirement date | Deprecated model | Recommended replacement |
| - | - | - |
| November 30, 2026 | `claude-y-2` | `claude-new` |
"""
    with pytest.raises(bm.LayoutError):
        bm.parse_anthropic(text, "U", OV)


def test_gemini_tables_and_routing():
    text = """
{% callout %}
Effective December 1, 2026, all API requests to `gem-old` will automatically route to
[`gem-new`](/docs/models/gem-new) and be billed at its rates.
{% /callout %}

{% table %}
  * Model
  * Release date
  * Shutdown date
  * Recommended replacement

  ---

  * `gem-old`
  * June 17, 2025
  * December 1, 2026
  * `gem-new`

  ---

  * `gem-current`
  * May 1, 2026
  * No shutdown date announced
  *
{% /table %}
"""
    (e,) = bm.parse_gemini(text, "U", OV)
    assert (e["ids"], e["shutdown"], e["after_shutdown"], e["routes_to"]) == (
        ["gem-old"], "2026-12-01", "routes", "gem-new")


def test_vertex_html_table():
    text = """<table><tr><th>Model ID</th><th>Release date</th><th>Retirement date</th><th>Replacement model ID</th></tr>
<tr><td><a href="#"><code>gem-a</code></a></td><td>June 17, 2025</td><td>October 20, 2026</td>
<td><a><code>gem-b</code></a> or <a><code>gem-c</code></a></td></tr>
<tr><td><code>gem-b</code></td><td>May 1, 2026</td><td>May 1, 2027 or later</td><td></td></tr>
<tr><td><code>emb@003*</code></td><td>x</td><td>April 1, 2027</td><td></td></tr></table>"""
    out = bm.parse_vertex(text, "U", OV)
    assert [(e["ids"], e["shutdown"], e["replacement"]) for e in out] == [
        (["gem-a"], "2026-10-20", "gem-b or gem-c"),
        (["emb@003"], "2027-04-01", None),
    ]


def test_azure_footnotes_are_stripped_from_every_cell():
    # The live page puts footnote markers on replacements too ("gpt-5.6-sol^4^"),
    # which v0.4.0 and v0.4.1 kept in the data.
    text = """
### Azure OpenAI

| Model | Version | Lifecycle | Retirement date | Replacement |
| --- | --- | --- | --- | --- |
| o3 | 2025-04-16 | Deprecated | 2026-11-19 | gpt-5.6-sol^4^ |
| o3-mini^5^ | 2025-01-31^5^ | Deprecated^5^ | 2026-11-19^4^ | gpt-5.6-terra^4^ (2026-07-09) |

### Next section
"""
    out = bm.parse_azure(text, "U", OV)
    assert [(e["ids"], e["aliases"], e["version"], e["shutdown"], e["replacement"]) for e in out] == [
        (["o3-2025-04-16"], ["o3"], "2025-04-16", "2026-11-19", "gpt-5.6-sol"),
        (["o3-mini-2025-01-31"], ["o3-mini"], "2025-01-31", "2026-11-19", "gpt-5.6-terra"),
    ]
    for e in out:
        assert "^" not in json.dumps(e)


def test_shipped_data_has_no_footnote_markers():
    data = json.loads(bm.OUT.read_text(encoding="utf-8"))
    assert "^" not in json.dumps(data["models"])


def test_azure_table():
    text = """
### Azure OpenAI

| Model | Version | Lifecycle | Retirement date | Replacement |
| --- | --- | --- | --- | --- |
| gpt-x | 2024-05-13 | Deprecated | 2027-01-14^2^ | gpt-y (2025-11-13) |
| gpt-x | 2024-08-06 | Legacy | 2027-04-14^3^ | gpt-y |
| gpt-y | 2025-11-13 | GA | 2027-07-13 | — |

### Next section
"""
    out = bm.parse_azure(text, "U", OV)
    assert [(e["ids"], e["aliases"], e["shutdown"], e["replacement"]) for e in out] == [
        (["gpt-x-2024-05-13"], ["gpt-x"], "2027-01-14", "gpt-y"),
        (["gpt-x-2024-08-06"], ["gpt-x"], "2027-04-14", "gpt-y"),
    ]


def test_bedrock_lists():
    text = """
**Models with a scheduled EOL date**

- **Anthropic**
  - **Model name:** Claude A
  - **Model ID:** anthropic.claude-a-v1:0
  - **Regions:** us-east-1, us-west-2 / **Legacy date:** October 10, 2026 / **EOL date:** November 13, 2026 / **Public extended access start date:** October 10, 2026
  - **Regions:** ca-central-1 / **Legacy date:** October 15, 2026 / **EOL date:** November 27, 2026 / **Public extended access start date:** October 15, 2026

- **DeepSeek**
  - **Model name:** DeepSeek-V3.1
  - **Model ID:** deepseek.v3-v1:0 (bedrock-runtime), deepseek.v3.1 (bedrock-mantle)
  - **Regions:** us-east-2
  - **Legacy date:** September 30, 2026
  - **EOL date:** March 30, 2027
"""
    out = bm.parse_bedrock(text, "U", OV)
    a, d = out
    assert a["ids"] == ["anthropic.claude-a-v1:0"]
    assert a["shutdown"] == "2026-11-13"
    assert [g["date"] for g in a["regions"]] == ["2026-11-13", "2026-11-27"]
    assert d["ids"] == ["deepseek.v3-v1:0", "deepseek.v3.1"]
    assert d["regions"] == [{"regions": ["us-east-2"], "date": "2027-03-30"}]


def test_too_few_rows_is_a_layout_error(tmp_path, monkeypatch):
    for fname in ("openai.md", "anthropic.md", "gemini.md", "vertex-versions.html", "azure.md", "bedrock.md"):
        (tmp_path / fname).write_text("nothing here", encoding="utf-8")
    with pytest.raises(bm.LayoutError):
        bm.build(tmp_path, "2026-11-19")
