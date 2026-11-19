"""0.4.0: retirements from OpenAI, Anthropic, Gemini API, Vertex AI, Azure OpenAI and
Amazon Bedrock (LC001 from data/models.json), plus LC005 and LC006."""

import json
import textwrap
from pathlib import Path

import pytest

from luna_check import models
from luna_check.scanner import scan

PROVIDERS = Path(__file__).parent / "fixtures" / "providers"
OFFICIAL = (
    "https://developers.openai.com/",
    "https://platform.claude.com/",
    "https://ai.google.dev/",
    "https://docs.cloud.google.com/",
    "https://learn.microsoft.com/",
    "https://docs.aws.amazon.com/",
)


def write(tmp_path, name, body):
    p = tmp_path / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(textwrap.dedent(body).lstrip("\n"), encoding="utf-8")
    return p


def found(path):
    findings, _ = scan(path, include_tests=True)
    return findings


def hits(path):
    return {(f.path, f.line, f.rule.id, f.severity) for f in found(path)}


# --- the data -------------------------------------------------------------------

def test_every_entry_cites_an_official_page():
    data = json.loads(models.DATA.read_text(encoding="utf-8"))
    assert set(data["sources"]) == {"openai", "anthropic", "gemini-api", "vertex", "azure", "bedrock"}
    for e in data["models"]:
        assert e["source"].startswith(OFFICIAL), e
        assert e["ids"] and e["checked"]


@pytest.mark.parametrize("model_id, platform, date", [
    ("claude-sonnet-4-5-20250929", "anthropic", "2026-11-30"),
    ("gemini-2.5-pro", "gemini-api", "2026-12-01"),
    ("gemini-2.5-flash", "gemini-api", "2026-12-01"),
    ("gpt-4o-2024-08-06", "openai", "2027-01-14"),
    ("gemini-2.5-pro", "vertex", "2026-10-20"),
    ("anthropic.claude-sonnet-4-5-20250929-v1:0", "bedrock", "2027-04-08"),
])
def test_key_dates(model_id, platform, date):
    entries = [e for e, _ in models.catalog().index[model_id] if e["platform"] == platform]
    assert [e["shutdown"] for e in entries] == [date]


# --- one fixture folder per provider ------------------------------------------------

def test_anthropic_fixtures():
    assert hits(PROVIDERS / "anthropic") == {
        ("app.py", 5, "LC001", "high"),     # claude-sonnet-4-5 (alias of the Sep 29 snapshot)
        ("app.py", 12, "LC005", "high"),    # temperature=0.2
        ("app.py", 19, "LC001", "high"),    # claude-3-5-haiku-20241022, retired
        ("chat.ts", 7, "LC001", "high"),
        ("chat.ts", 9, "LC005", "high"),    # top_p
        ("llm.go", 11, "LC001", "high"),
        ("llm.go", 13, "LC005", "high"),    # Temperature: anthropic.Float(0.5)
    }
    msg = {(f.path, f.line): f.message for f in found(PROVIDERS / "anthropic")}
    assert "Nov 30, 2026" in msg[("chat.ts", 7)]
    assert '"claude-sonnet-5-5"' in msg[("chat.ts", 7)]


def test_gemini_api_fixtures():
    fs = {f.line: f for f in found(PROVIDERS / "gemini_api")}
    assert set(fs) == {9, 13}
    assert "From Dec 1, 2026" in fs[9].message and '"gemini-3.8-flash"' in fs[9].message
    assert "was shut down on Jun 1, 2026" in fs[13].message  # models/gemini-2.0-flash
    assert fs[9].source.startswith("https://ai.google.dev/")


def test_vertex_fixtures():
    fs = {f.line: f for f in found(PROVIDERS / "vertex")}
    assert set(fs) == {7, 11}
    assert "Oct 20, 2026 (Vertex AI)" in fs[7].message


def test_azure_fixtures():
    fs = {f.line: f for f in found(PROVIDERS / "azure")}
    assert set(fs) == {12, 21}  # gpt-35-turbo is not on Azure's schedule page
    assert "version 2024-05-13 retires on Jan 14, 2027" in fs[12].message
    assert "2024-08-06, 2024-11-20 retire on Apr 14, 2027" in fs[12].message


def test_bedrock_fixtures():
    fs = {f.line: f for f in found(PROVIDERS / "bedrock")}
    assert set(fs) == {7, 8}  # us. cross-Region prefix included
    assert "Apr 8, 2027" in fs[7].message and "us-gov-east-1" in fs[7].message


def test_openai_endpoint_fixtures():
    assert hits(PROVIDERS / "openai") == {
        ("endpoints.py", 7, "LC006", "high"),   # beta.assistants
        ("endpoints.py", 11, "LC006", "high"),  # beta.threads
        ("endpoints.py", 17, "LC006", "high"),  # pmpt_ prompt object
        ("endpoints.py", 22, "LC001", "high"),  # whisper-1
        ("endpoints.py", 22, "LC006", "high"),  # audio.translations
        ("endpoints.py", 25, "LC006", "high"),  # OpenAI-Beta: realtime=v1
        ("raw.js", 3, "LC006", "high"),         # /v1/assistants
        ("raw.js", 4, "LC006", "high"),         # assistants=v2
    }


# --- platform choice ------------------------------------------------------------------

def test_gemini_id_without_platform_notes_vertex(tmp_path):
    write(tmp_path, "config.yaml", "model: gemini-2.5-pro\n")
    (f,) = found(tmp_path)
    assert "From Dec 1, 2026" in f.message
    assert "On Vertex AI: retired Oct 20, 2026." in f.message


def test_gemini_api_client_with_key_is_the_gemini_api(tmp_path):
    write(tmp_path, "a.py", 'client = genai.Client(api_key=key)\nm = "gemini-2.5-pro"\n')
    write(tmp_path, "b.ts", 'const ai = new GoogleGenAI({ apiKey: k });\nconst m = "gemini-2.5-pro";\n')
    for f in found(tmp_path):
        assert "From Dec 1, 2026" in f.message and "Vertex" not in f.message


def test_azure_only_ids_need_an_azure_file(tmp_path):
    write(tmp_path, "a.py", 'm = "codex-mini-2025-05-16"\n')  # only Azure lists it
    assert found(tmp_path) == []
    write(tmp_path, "b.py", 'from openai import AzureOpenAI\nm = "codex-mini-2025-05-16"\n')
    assert [f.path for f in found(tmp_path)] == ["b.py"]


def test_duplicate_rows_use_the_later_shutdown(tmp_path):
    # gpt-4-0314 is listed twice on OpenAI's page: an early estimate and the shutdown.
    write(tmp_path, "a.py", 'm = "gpt-4-0314"\n')
    (f,) = found(tmp_path)
    assert "Mar 26, 2026" in f.message


def test_message_follows_the_date(tmp_path, monkeypatch):
    write(tmp_path, "a.py", 'm = "claude-sonnet-4-5-20250929"\n')
    assert "shuts down on Nov 30, 2026" in found(tmp_path)[0].message
    monkeypatch.setenv("LUNA_CHECK_TODAY", "2026-12-01")
    assert "was shut down on Nov 30, 2026" in found(tmp_path)[0].message


def test_routed_model_is_low_after_the_date(tmp_path, monkeypatch):
    monkeypatch.setenv("LUNA_CHECK_TODAY", "2026-12-02")
    write(tmp_path, "a.py", 'from google import genai\nc = genai.Client(api_key=k)\nm = "gemini-2.5-flash"\n')
    (f,) = found(tmp_path)
    assert (f.severity, f.low_reason) == ("low", "routed to a newer model")


def test_deprecated_without_date_is_low(tmp_path):
    write(tmp_path, "a.py", 'm = "claude-mythos-preview"\n')
    (f,) = found(tmp_path)
    assert (f.severity, f.low_reason) == ("low", "no date yet")


@pytest.mark.parametrize("line", [
    'ok = name.startswith("gpt-4")',
    'ok = strings.HasPrefix(name, "gpt-4")',
    'ok = "gpt-4" in name',
    'ok = name.startswith(("gpt-4", "o1"))',
])
def test_name_tests_are_not_model_use(tmp_path, line):
    write(tmp_path, "a.py", line + "\n")
    assert found(tmp_path) == []


# --- LC005 ------------------------------------------------------------------------------

def test_claude_sampling_needs_an_anthropic_file(tmp_path):
    write(tmp_path, "a.py", 'client.messages.create(model=m, temperature=0.2)\n')
    assert found(tmp_path) == []


def test_openai_thread_messages_are_not_claude(tmp_path):
    write(tmp_path, "a.py", '''
        import anthropic
        client.beta.threads.messages.create(thread_id=t, temperature=0.2)
    ''')
    assert [f.rule.id for f in found(tmp_path)] == []


def test_claude_sampling_langchain_and_batches(tmp_path):
    write(tmp_path, "a.py", '''
        from langchain_anthropic import ChatAnthropic
        import anthropic
        llm = ChatAnthropic(model=m, temperature=0)
        client.messages.batches.create(requests=[{"custom_id": "a", "params": {"model": m, "top_k": 5}}])
    ''')
    assert [(f.line, f.rule.id) for f in found(tmp_path)] == [(3, "LC005"), (4, "LC005")]


def test_claude_sampling_raw_http(tmp_path):
    write(tmp_path, "a.js", '''
        const body = { model: m, max_tokens: 10, "temperature": 0.7 };
        await fetch("https://api.anthropic.com/v1/messages", { method: "POST", body: JSON.stringify(body) });
    ''')
    assert [(f.line, f.rule.id) for f in found(tmp_path)] == [(1, "LC005")]


# --- LC006 ------------------------------------------------------------------------------

def test_endpoint_calls_need_an_openai_file(tmp_path):
    write(tmp_path, "a.py", 'client.beta.assistants.create(name="x")\n')
    assert found(tmp_path) == []


def test_evals_become_read_only(tmp_path):
    write(tmp_path, "a.py", 'from openai import OpenAI\nclient.evals.create(name="x")\nclient.evals.list()\n')
    (f,) = found(tmp_path)
    assert (f.line, f.rule.id) == (2, "LC006")
    assert "becomes read-only on Nov 30, 2026" in f.message


def test_videos_api_was_shut_down(tmp_path):
    write(tmp_path, "a.ts", 'import OpenAI from "openai";\nawait client.videos.create({ model: "sora-2" });\n')
    rules_found = sorted(f.rule.id for f in found(tmp_path))
    assert rules_found == ["LC001", "LC006"]  # sora-2 is listed too
