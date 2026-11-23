"""Mistral AI, DeepSeek, xAI, Cohere and Groq (added in 0.5.0).

Parser tests use small snippets in each page's format with made-up rows. Scan
tests use the shipped models.json, with today pinned (conftest: 2026-11-19).
"""

import importlib.util
import textwrap
from pathlib import Path

import pytest

from luna_check import models
from luna_check.cli import main
from luna_check.scanner import scan

SPEC = importlib.util.spec_from_file_location(
    "build_models", Path(__file__).resolve().parent.parent / "scripts" / "build_models.py"
)
bm = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(bm)

OV = {"exclude_ids": []}


def write(tmp_path, name, body):
    p = tmp_path / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(textwrap.dedent(body).lstrip("\n"), encoding="utf-8")
    return p


def found(path):
    findings, _ = scan(path, include_tests=True)
    return findings


def hits(path):
    return sorted((f.path, f.line, f.severity) for f in found(path))


# --- parsers ----------------------------------------------------------------------

def test_mistral_replacement_link_becomes_the_api_name():
    text = """
| Model | API name | Status | Context | Summary |
| --- | --- | --- | --- | --- |
| [Model New](/models/new-1) | `m-new` | GA | 1M | x |

## Deprecated and retired models

| Model | API name | Status | Context | Summary | Deprecation | Retirement | Replacement |
| --- | --- | --- | --- | --- | --- | --- | --- |
| [Model Old](/models/old-1) | `m-old` | Deprecated | 1M | x | 2026-05-22 | 2026-07-31 | [Model New](/models/new-1) |
| [Model Mid](/models/mid-1) | `m-mid` | Retired | 1M | x | April 30, 2026 | July 31, 2026 | [Model Old](/models/old-1) |
| [Model Mid Again](/models/mid-2) | `m-mid` | Retired | 1M | x | April 30, 2026 | July 31, 2026 | [Model New](/models/new-1) |
| [No API name](/models/x) |  | Retired | 1M | x |  |  | [Model New](/models/new-1) |
| [Model Lone](/models/lone) | `m-lone` | Deprecated | 1M | x | 2026-09-29 | 2026-09-30 |  |
"""
    out = {e["ids"][0]: e for e in bm.parse_mistral(text, "U", OV)}
    assert set(out) == {"m-old", "m-mid", "m-lone"}
    assert out["m-old"]["replacement"] == "m-new"
    assert out["m-mid"]["shutdown"] == "2026-07-31"
    assert out["m-mid"]["replacement"] == "m-old or m-new"  # listed twice: both replacements
    assert out["m-lone"]["replacement"] is None
    assert {e["behavior"] for e in out.values()} == {"error"}


def test_mistral_unknown_replacement_is_a_layout_error():
    text = """
| Model | API name | Status | Context | Summary | Deprecation | Retirement | Replacement |
| --- | --- | --- | --- | --- | --- | --- | --- |
| [Old](/models/old) | `m-old` | Deprecated | 1M | x | 2026-05-22 | 2026-07-31 | [Gone](/models/gone) |
"""
    with pytest.raises(bm.LayoutError):
        bm.parse_mistral(text, "U", OV)


def test_deepseek_change_log():
    text = """# Change Log

## Date: 2026-09-10

### New Flash

Change the model name to `ds-new` to call it. The previous models have been retired; for compatibility,
the model names `ds-a` and `ds-b` are temporarily routed to New Flash.

## Date: 2026-04-24

### V4

The model parameter should be set to `ds-pro` or `ds-a`.

The two legacy API model names, `ds-chat` and `ds-reasoner`, will be discontinued in three months (2026-07-24).
"""
    out = {e["ids"][0]: e for e in bm.parse_deepseek(text, "U", OV)}
    assert (out["ds-a"]["shutdown"], out["ds-a"]["behavior"], out["ds-a"]["routes_to"]) == (
        "2026-09-10", "redirect", "ds-new")
    assert out["ds-b"]["routes_to"] == "ds-new"
    assert (out["ds-chat"]["shutdown"], out["ds-chat"]["behavior"], out["ds-chat"]["replacement"]) == (
        "2026-07-24", "error", "ds-pro or ds-a")
    assert set(out) == {"ds-a", "ds-b", "ds-chat", "ds-reasoner"}


def test_xai_guide_and_release_notes():
    guide = """# Retirement

**Effective May 15, 2026 at 12:00 PM PT**, the following models will be retired:

| Model being retired | Redirect target after May 15 |
|---|---|
| `x-fast-reasoning` | `x-new` with `low` reasoning effort |
| `x-code` | `x-build` |
| `x-image-pro` | `x-image-quality` |
"""
    notes = """# Release Notes

### x-build end of life

`x-build` reached end of life on November 19, 2026 and is no longer served on the API.

### x-image-quality retired

Requests to `x-image-quality` and `x-image-pro` are now served by `x-image-2-low`: lower price.

### x-voice-1 end of life

`x-voice-1` is deprecated and reaches end of life on October 2, 2026. All requests to that slug are routed to `x-voice-2` at the same price.

### x-talk deprecation

`x-talk` is deprecated. To upgrade, set `model` to `x-talk-3` or `x-talk-latest`, at the same price.

### x-image-quality retirement

On November 2, 2026, `x-image-quality` is retired. Requests to the slug will be served by `x-image-2` with `quality` set to `low`.
"""
    out = {e["ids"][0]: e for e in bm.parse_xai([(guide, "G"), (notes, "N")], OV)}
    e = out["x-fast-reasoning"]
    assert (e["shutdown"], e["behavior"], e["routes_to"], e["routes_effort"], e["source"]) == (
        "2026-05-15", "redirect", "x-new", "low", "G")
    assert out["x-code"]["routes_to"] == "x-build"
    assert (out["x-build"]["shutdown"], out["x-build"]["behavior"]) == ("2026-11-19", "error")
    # The later "now served by" notice wins over the guide's redirect target.
    assert out["x-image-pro"]["routes_to"] == "x-image-2-low"
    assert (out["x-image-quality"]["shutdown"], out["x-image-quality"]["replacement"],
            out["x-image-quality"]["routes_to"]) == ("2026-11-02", "x-image-2", "x-image-2-low")
    assert (out["x-voice-1"]["behavior"], out["x-voice-1"]["routes_to"]) == ("redirect", "x-voice-2")
    assert (out["x-talk"]["shutdown"], out["x-talk"]["replacement"]) == (None, "x-talk-3 or x-talk-latest")


def test_cohere_sections():
    text = """
## Deprecation History

### 2026-04-04: Old embed

Effective April 4th, 2026, the following models will be retired:

* `embed-old-v2.0`
* `aya-old-8b`

We encourage you to migrate:

* Embedding tasks alternatives:
  * `embed-new-v4.0`
* Chat tasks alternatives:
  * `chat-new-a`
  * `chat-new-b`

### 2025-09-15: Older command models

Deprecated Models:

* `command-old-03-2024`  (and the alias `command-old`)
* `command`
* `summarize` (Refer to [the guide](https://example.com) for alternatives).

For command model replacements, we recommend you use `command-new-08-2024`, or `command-a-03-2025` (strongest) instead.

### 2024-12-02: Rerank v2.0

| Shutdown Date | Deprecated Model | Deprecated Model Price | Recommended Replacement |
| ------------- | ---------------- | ---------------------- | ----------------------- |
| 2025-04-30    | `rerank-old-v2.0` | \\$1.00 / 1K searches | `rerank-v3.5` |
"""
    out = {e["ids"][0]: e for e in bm.parse_cohere(text, "U", OV)}
    assert (out["embed-old-v2.0"]["shutdown"], out["embed-old-v2.0"]["replacement"]) == (
        "2026-04-04", "embed-new-v4.0")
    assert out["aya-old-8b"]["replacement"] == "chat-new-a or chat-new-b"
    assert (out["command-old-03-2024"]["shutdown"], out["command-old-03-2024"]["aliases"],
            out["command-old-03-2024"]["replacement"]) == (None, ["command-old"],
                                                         "command-new-08-2024 or command-a-03-2025")
    assert out["summarize"]["replacement"] is None
    assert (out["rerank-old-v2.0"]["shutdown"], out["rerank-old-v2.0"]["replacement"]) == ("2025-04-30", "rerank-v3.5")
    assert {e["behavior"] for e in out.values()} == {"error"}


def test_groq_tables():
    text = """
### [September 21, 2026: compound](#x)

| Deprecated Model   | Shutdown Date | Recommended Replacement Model ID |
| ------------------ | ------------- | -------------------------------- |
| groq/old           | 09/21/26      | —                                |
| llama-old          | 1/6/25        | model-a or model-b               |

### [April 14, 2025: many](#y)

| Model ID         | Shutdown Date | Recommended Replacement Model ID                    |
| ---------------- | ------------- | --------------------------------------------------- |
| text-preview     | 11/25/24      | vision-preview llama-text (text-only workloads)     |
| dup-specdec      | 04/14/25      | x                                                   |
| dup-specdec      | 03/24/25      | y                                                   |
"""
    out = {e["ids"][0]: e for e in bm.parse_groq(text, "U", OV)}
    assert (out["groq/old"]["shutdown"], out["groq/old"]["replacement"]) == ("2026-09-21", None)
    assert (out["llama-old"]["shutdown"], out["llama-old"]["replacement"]) == ("2025-01-06", "model-a or model-b")
    assert out["text-preview"]["replacement"] == "vision-preview or llama-text"
    assert (out["dup-specdec"]["shutdown"], out["dup-specdec"]["replacement"]) == ("2025-04-14", "x")


@pytest.mark.parametrize("model_id, platform, shutdown, behavior", [
    ("mistral-large-2411", "mistral", "2026-05-31", "error"),
    ("deepseek-chat", "deepseek", "2026-07-24", "error"),
    ("deepseek-reasoner", "deepseek", "2026-07-24", "error"),
    ("deepseek-v4-flash", "deepseek", "2026-09-10", "redirect"),
    ("grok-3", "xai", "2026-05-15", "redirect"),
    ("grok-4-0709", "xai", "2026-05-15", "redirect"),
    ("grok-build-0.1", "xai", "2026-11-19", "error"),
    ("embed-english-v2.0", "cohere", "2026-04-04", "error"),
    ("command-r-03-2024", "cohere", None, "error"),
    ("llama-3.3-70b-versatile", "groq", "2026-08-16", "error"),
    ("qwen/qwen3-32b", "groq", "2026-07-17", "error"),
    ("meta-llama/llama-4-maverick-17b-128e-instruct", "groq", "2026-03-09", "error"),
    ("moonshotai/kimi-k2-instruct-0905", "groq", "2026-04-15", "error"),
])
def test_shipped_data(model_id, platform, shutdown, behavior):
    (e,) = [e for e, _ in models.catalog().index[model_id] if e["platform"] == platform]
    assert (e["shutdown"], e["behavior"]) == (shutdown, behavior)


# --- one positive and one negative scan per provider -------------------------------

def test_mistral_positive(tmp_path):
    write(tmp_path, "a.py", 'from mistralai import Mistral\nMistral().chat.complete(model="mistral-large-2411")\n')
    (f,) = found(tmp_path)
    assert (f.line, f.severity) == (2, "high")
    assert '"mistral-large-2411" was shut down on May 31, 2026 (Mistral AI API)' in f.message
    assert 'Replace it with "mistral-medium-3-5"' in f.message
    assert f.source == "https://docs.mistral.ai/models"


def test_mistral_negative(tmp_path):
    write(tmp_path, "a.py", """
        Mistral().chat.complete(model="mistral-large-4")
        Mistral().chat.complete(model="mistral-small-2603")
        log("mistral-large-2411 is retired, see docs")
    """)
    assert found(tmp_path) == []


def test_deepseek_positive(tmp_path):
    write(tmp_path, "a.ts", 'const r = await ds.chat.completions.create({ model: "deepseek-reasoner" });\n')
    (f,) = found(tmp_path)
    assert f.severity == "high"
    assert '"deepseek-reasoner" was shut down on Jul 24, 2026 (DeepSeek API), so requests to it fail.' in f.message
    # The listed replacement deepseek-v4-flash was itself retired later: say so.
    assert '"deepseek-v4-flash" was itself retired on Sep 10, 2026 and now redirects to "deepseek-flash"' in f.message


def test_deepseek_negative(tmp_path):
    write(tmp_path, "a.py", 'c.create(model="deepseek-flash")\nc.create(model="deepseek-v4-pro")\n')
    assert found(tmp_path) == []


def test_xai_redirect_is_medium(tmp_path):
    write(tmp_path, "a.py", 'client.chat.completions.create(model="grok-3", messages=m)\n')
    (f,) = found(tmp_path)
    assert f.severity == "medium"
    assert f.message == ('"grok-3" was retired on May 15, 2026 (xAI API) and now silently redirects to '
                         '"grok-4.3" with "none" reasoning effort: a different model, so output and '
                         "pricing can change.")


def test_xai_reasoning_slug_gets_low_effort(tmp_path):
    write(tmp_path, "a.go", 'package x\nvar req = Request{Model: "grok-4-1-fast-reasoning"}\n')
    (f,) = found(tmp_path)
    assert f.severity == "medium"
    assert 'redirects to "grok-4.3" with "low" reasoning effort' in f.message


def test_xai_redirect_to_a_model_that_is_gone_is_high(tmp_path, monkeypatch):
    # grok-code-fast-1 redirects to grok-build-0.1, which reached end of life on Nov 19, 2026.
    monkeypatch.setenv("LUNA_CHECK_TODAY", "2026-11-23")
    write(tmp_path, "a.py", 'c.create(model="grok-code-fast-1")\n')
    (f,) = found(tmp_path)
    assert f.severity == "high"
    assert "which itself reached end of life on Nov 19, 2026" in f.message
    assert "may fail" in f.message


def test_xai_negative(tmp_path):
    write(tmp_path, "a.py", 'c.create(model="grok-4.3")\nc.create(model="grok-4.7")\nname = "grok-3 fans"\n')
    assert found(tmp_path) == []


def test_cohere_positive(tmp_path):
    write(tmp_path, "a.py", 'co.embed(model="embed-english-v2.0", texts=t)\n')
    (f,) = found(tmp_path)
    assert f.severity == "high"
    assert 'Replace it with "embed-english-v3.0" or "embed-multilingual-v3.0" or "embed-v4.0"' in f.message


def test_cohere_deprecated_without_date_is_low(tmp_path):
    write(tmp_path, "a.py", 'co.chat(model="command-r", messages=m)\n')
    (f,) = found(tmp_path)
    assert (f.severity, f.low_reason) == ("low", "no date yet")


def test_cohere_negative(tmp_path):
    write(tmp_path, "a.py", 'co.chat(model="command-a-03-2025")\nco.chat(model="command-r-08-2024")\n')
    assert found(tmp_path) == []


def test_groq_positive(tmp_path):
    write(tmp_path, "a.js", 'groq.chat.completions.create({ model: "qwen/qwen3-32b", messages });\n')
    (f,) = found(tmp_path)
    assert f.severity == "high"
    assert '"qwen/qwen3-32b" was shut down on Jul 17, 2026 (GroqCloud)' in f.message
    assert 'Replace it with "openai/gpt-oss-120b"' in f.message


def test_groq_negative(tmp_path):
    write(tmp_path, "a.js", 'groq.chat.completions.create({ model: "openai/gpt-oss-120b" });\n'
                            'const other = "meta-llama/llama-4-maverick-17b-128e-instruct-fp8";\n')
    assert found(tmp_path) == []


# --- short IDs that are everyday words ------------------------------------------------

@pytest.mark.parametrize("name, body", [
    ("a.py", 'parser.add_argument("command")\n'),
    ("b.py", 'step = {"type": "command", "run": x}\n'),
    ("c.py", 'action = "summarize"\nif mode == "command": pass\n'),
    ("d.ts", 'switch (k) { case "command": break; }\nconst icon = "command-light";\n'),
    ("e.go", 'package x\nvar c = exec.Command("command")\n'),
    ("f.py", 'model = "/usr/bin/command"\n'),
    ("g.py", 'keys = {"reload": "command-r"}\n'),
])
def test_word_ids_are_not_reported_outside_a_model_setting(tmp_path, name, body):
    write(tmp_path, name, body)
    assert found(tmp_path) == []


@pytest.mark.parametrize("name, body", [
    ("a.py", 'co.chat(model="command", messages=m)\n'),
    ("b.py", 'DEFAULT_MODEL = "command-light"\n'),
    ("c.ts", "const r = await co.chat({ model: 'command-r-plus' });\n"),
    ("d.go", 'package x\nvar req = ChatRequest{Model: "command"}\n'),
    ("e.py", 'cfg = {"model": "cohere/command-r"}\n'),
    ("f.go", 'package x\nfunc f() { model := "summarize"; use(model) }\n'),
    ("g.yaml", "llm:\n  model: command\n"),
])
def test_word_ids_are_reported_as_a_model_setting(tmp_path, name, body):
    write(tmp_path, name, body)
    (f,) = found(tmp_path)
    assert f.rule.id == "LC001"


# --- MEDIUM in reports, exit codes and lower-priority files ----------------------------

def test_redirect_after_date_is_medium_in_the_text_report(tmp_path, capsys):
    write(tmp_path, "a.py", 'c.create(model="grok-3")\n')
    assert main([str(tmp_path)]) == 0  # MEDIUM alone does not fail the run
    out = capsys.readouterr().out
    assert "line 1  MEDIUM  LC001" in out
    assert "Found 0 high, 1 medium, 0 low in 1 file(s)." in out


def test_redirect_before_the_date_is_medium(tmp_path, monkeypatch):
    monkeypatch.setenv("LUNA_CHECK_TODAY", "2026-09-01")
    write(tmp_path, "a.py", 'c.create(model="deepseek-v4-flash")\n')
    (f,) = found(tmp_path)
    assert f.severity == "medium"
    assert '"deepseek-v4-flash" retires on Sep 10, 2026 (DeepSeek API). After that, requests to it are ' \
           'silently redirected to "deepseek-flash"' in f.message


def test_medium_in_a_seed_file_is_low(tmp_path):
    write(tmp_path, "seed/data.py", 'c.create(model="grok-3")\n')
    (f,) = found(tmp_path)
    assert (f.severity, f.low_reason) == ("low", "seed/demo file")


def test_medium_in_a_model_list_is_low(tmp_path):
    write(tmp_path, "a.py", 'MODELS = ["grok-3", "grok-4.3", "grok-4.7", "grok-4-fast-reasoning"]\n')
    assert {f.severity for f in found(tmp_path)} == {"low"}
