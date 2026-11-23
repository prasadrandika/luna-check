"""scripts/refresh_models.py: the weekly refresh decides between a PR, an issue or nothing."""

import copy
import importlib.util
import json
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))
SPEC = importlib.util.spec_from_file_location("refresh_models", SCRIPTS / "refresh_models.py")
rm = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(rm)


def entry(platform, ids, shutdown="2027-01-14", **kw):
    e = {"platform": platform, "ids": ids, "status": "deprecated", "shutdown": shutdown,
         "replacement": "new-model", "behavior": "error",
         "source": f"https://example.test/{platform}", "checked": "2026-11-19"}
    e.update(kw)
    return e


def data(models):
    return {"schema": 1, "sources": {}, "models": models}


OLD = data(
    [entry("openai", [f"gpt-old-{i}"]) for i in range(10)]
    + [entry("anthropic", [f"claude-old-{i}"]) for i in range(4)]
)


@pytest.fixture
def committed(tmp_path):
    p = tmp_path / "models.json"
    p.write_text(json.dumps(OLD), encoding="utf-8")
    return p


def fake_build(monkeypatch, new):
    monkeypatch.setattr(rm.build_models, "build", lambda pages, today: copy.deepcopy(new))


def test_only_checked_dates_differ_is_unchanged(tmp_path, committed, monkeypatch):
    new = copy.deepcopy(OLD)
    for e in new["models"]:
        e["checked"] = "2026-11-23"
    fake_build(monkeypatch, new)
    assert rm.run(today="2026-11-23", out_dir=tmp_path / "out", data_path=committed) == "unchanged"
    assert json.loads(committed.read_text(encoding="utf-8")) == OLD  # untouched
    assert not (tmp_path / "out" / "pr-body.md").exists()


def test_changes_write_data_and_pr_body(tmp_path, committed, monkeypatch):
    new = copy.deepcopy(OLD)
    new["models"][0]["shutdown"] = "2027-02-01"            # changed
    new["models"] = [e for e in new["models"] if e["ids"] != ["gpt-old-9"]]  # removed
    new["models"].append(entry("gemini-api", ["gemini-x"], "2026-12-01",
                               behavior="redirect", routes_to="gemini-y"))  # added
    fake_build(monkeypatch, new)
    assert rm.run(today="2026-11-23", out_dir=tmp_path, data_path=committed) == "changed"
    assert json.loads(committed.read_text(encoding="utf-8")) == new
    body = (tmp_path / "pr-body.md").read_text(encoding="utf-8")
    assert "**1 added, 1 changed, 1 removed.**" in body
    assert "| gemini-api | `gemini-x` | 2026-12-01 | new-model | [source](https://example.test/gemini-api) |" in body
    assert "| openai | `gpt-old-0` | `shutdown` | 2027-01-14 | 2027-02-01 |" in body
    assert "| openai | `gpt-old-9` | 2027-01-14 |" in body


def test_far_fewer_rows_opens_an_issue(tmp_path, committed, monkeypatch):
    new = copy.deepcopy(OLD)
    new["models"] = [e for e in new["models"] if e["platform"] != "openai" or e["ids"][0] < "gpt-old-3"]
    fake_build(monkeypatch, new)  # openai: 3 rows now, 10 before
    assert rm.run(today="2026-11-23", out_dir=tmp_path, data_path=committed) == "layout"
    assert json.loads(committed.read_text(encoding="utf-8")) == OLD  # untouched
    body = (tmp_path / "issue-body.md").read_text(encoding="utf-8")
    assert "`openai`: 3 rows now, 10 in the committed data" in body
    assert not (tmp_path / "pr-body.md").exists()


def test_a_platform_with_zero_rows_opens_an_issue(tmp_path, committed, monkeypatch):
    new = data([e for e in OLD["models"] if e["platform"] == "openai"])
    fake_build(monkeypatch, new)
    assert rm.run(today="2026-11-23", out_dir=tmp_path, data_path=committed) == "layout"
    assert "`anthropic`: 0 rows now" in (tmp_path / "issue-body.md").read_text(encoding="utf-8")


def test_parser_error_opens_an_issue(tmp_path, committed, monkeypatch):
    def boom(pages, today):
        raise rm.build_models.LayoutError("azure: no 'Azure OpenAI' section")
    monkeypatch.setattr(rm.build_models, "build", boom)
    assert rm.run(today="2026-11-23", out_dir=tmp_path, data_path=committed) == "layout"
    assert "azure: no 'Azure OpenAI' section" in (tmp_path / "issue-body.md").read_text(encoding="utf-8")


def test_fetch_error_opens_an_issue(tmp_path, committed, monkeypatch):
    def offline(pages, today):
        raise OSError("connection refused")
    monkeypatch.setattr(rm.build_models, "build", offline)
    assert rm.run(today="2026-11-23", out_dir=tmp_path, data_path=committed) == "layout"
    assert "could not fetch a page" in (tmp_path / "issue-body.md").read_text(encoding="utf-8")


def test_a_small_drop_is_a_normal_change(tmp_path, committed, monkeypatch):
    new = copy.deepcopy(OLD)
    new["models"] = new["models"][1:]  # openai 9 of 10: a removed row, not a layout change
    fake_build(monkeypatch, new)
    assert rm.run(today="2026-11-23", out_dir=tmp_path, data_path=committed) == "changed"


def test_bedrock_regions_are_readable_in_the_pr(tmp_path):
    old = data([entry("bedrock", ["meta.x-v1:0"], regions=[{"regions": ["us-east-1"], "date": "2027-03-30"}])])
    new = copy.deepcopy(old)
    new["models"][0]["regions"] = [{"regions": ["us-east-1", "us-west-2"], "date": "2027-04-30"}]
    body = rm.pr_body(rm.diff(old, new), new, "2026-11-23")
    assert "| `regions` | 2027-03-30 (1 regions) | 2027-04-30 (2 regions) |" in body
