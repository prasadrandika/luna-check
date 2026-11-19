"""The five real migrations.

Every problem a migration fixed must be found in the `before` version, and
the `after` version must be clean.

dsl, Nasiko and WeClaw have open-source licenses, so their files are copied
into tests/fixtures/real (see the README there). Basic-Rag and
youtube_transcription_api have no license, so their files are downloaded at
pinned commits when the tests run. Without network those tests are skipped,
unless LUNA_CHECK_REQUIRE_NETWORK=1 (set in CI), which makes them fail.
"""

import os
import urllib.request
from pathlib import Path

import pytest

from luna_check.scanner import scan

REAL = Path(__file__).parent / "fixtures" / "real"

NASIKO_AGENTS = ("books", "github", "hackernews", "weather")

EXPECTED_BEFORE = {
    "basic_rag": {("app.py", 49, "LC001")},
    "youtube_transcription_api": {
        ("app.py", 43, "LC002"),  # tiktoken.encoding_for_model("gpt-4o-mini")
        ("app.py", 73, "LC001"),  # model="gpt-4o-mini"
    },
    "dsl": {("llm/llm.go", 32, "LC001")},
    "nasiko": {
        (f"agents/{a}/llm.go", line, rule)
        for a in NASIKO_AGENTS
        for line, rule in ((96, "LC001"), (127, "LC004"))
    },
    "weclaw": {("agent/http_agent.go", 71, "LC001")},
}

# repo -> (GitHub repo, before commit, after commit, files changed by the migration)
REMOTE = {
    "basic_rag": (
        "prasadrandika/Basic-Rag",
        "4e7694725f513907b66474e9d0d3c653a174fdaf",
        "1c3d7a8e06b9d363efcff4a4856ebfb87c285d05",
        ("app.py",),
    ),
    "youtube_transcription_api": (
        "prasadrandika/youtube_transcription_api",
        "2303531a137becadd1c28a18e56644888c30dd9e",
        "6110bafd1e0376818a2df3633b1b6104049c703d",
        ("app.py",),
    ),
}


def _download(repo, side, dest):
    gh, before, after, files = REMOTE[repo]
    sha = before if side == "before" else after
    for name in files:
        url = f"https://raw.githubusercontent.com/{gh}/{sha}/{name}"
        try:
            with urllib.request.urlopen(url, timeout=30) as resp:
                data = resp.read()
        except OSError as e:
            if os.environ.get("LUNA_CHECK_REQUIRE_NETWORK") == "1":
                raise
            pytest.skip(f"could not download {url}: {e}")
        target = dest / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    return dest


@pytest.fixture
def repo_dir(tmp_path):
    def get(repo, side):
        if repo in REMOTE:
            return _download(repo, side, tmp_path / repo / side)
        return REAL / repo / side
    return get


def found(path, **kw):
    findings, _ = scan(path, **kw)
    return {(f.path, f.line, f.rule.id) for f in findings}


@pytest.mark.parametrize("repo", sorted(EXPECTED_BEFORE))
def test_before_finds_everything_the_migration_fixed(repo, repo_dir):
    assert found(repo_dir(repo, "before")) == EXPECTED_BEFORE[repo]


@pytest.mark.parametrize("repo", sorted(EXPECTED_BEFORE))
def test_after_is_clean(repo, repo_dir):
    assert found(repo_dir(repo, "after")) == set()


# grafana/ai-sdk (Apache-2.0) lists every OpenAI model ID it knows in a catalog,
# knownResponsesModelIDs. The file is copied unchanged from commit
# 9bf9d0b98913942d3438f616be308c77bbe9b016. Nothing there is the model the SDK
# sends, so every retired or retiring ID in it is LOW, not HIGH. The file also
# tests a model name as a prefix (strings.HasPrefix(modelID, "gpt-4")), which
# is not a model in use.
GRAFANA_JAN14_LINES = {139, 140, 141, 142, 145, 147, 148, 151, 152}
GRAFANA_CATALOG = range(136, 216)  # the knownResponsesModelIDs list


def test_model_catalog_is_low():
    findings, _ = scan(REAL / "grafana-ai-sdk")
    lines = {f.line for f in findings}
    assert {f.path for f in findings} == {"providers/openai/models.go"}
    assert {f.rule.id for f in findings} == {"LC001"}
    assert GRAFANA_JAN14_LINES <= lines
    assert all(line in GRAFANA_CATALOG for line in lines)
    assert {f.severity for f in findings} == {"low"}
    assert {f.low_reason for f in findings} == {"model list"}
