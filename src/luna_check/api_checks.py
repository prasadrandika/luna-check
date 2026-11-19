"""LC005 (Claude sampling parameters) and LC006 (retired OpenAI endpoints)."""

from __future__ import annotations

import re

from . import rules
from .checks import NULL_VALUE, Finding, _close_paren
from .lexer import GO, PY, Lexed
from .models import fmt, today

# --- LC005 Claude sampling parameters ---------------------------------------------

ANTHROPIC_FILE = re.compile(
    r"(?m)^\s*(?:import\s+anthropic\b|from\s+anthropic\b)|@anthropic-ai/sdk|anthropic-sdk-go|"
    r"langchain_anthropic|@langchain/anthropic|api\.anthropic\.com"
)
CLAUDE_CALL = re.compile(
    r"\b(?:messages\s*\.\s*(?:batches\s*\.\s*)?(?:create|stream|parse)|ChatAnthropic)\s*\("
)
GO_CLAUDE_PARAMS = re.compile(r"\b(?:Beta)?MessageNewParams\s*\{")
_ALT = "|".join(rules.CLAUDE_SAMPLING_PARAMS)
PY_KW = re.compile(rf"\b({_ALT})\s*=(?!=)")
JS_KEY = re.compile(rf"\b({_ALT})\s*:")
GO_FIELD = re.compile(r"\b(Temperature|TopP|TopK)\s*:")
GO_NAME = {"Temperature": "temperature", "TopP": "top_p", "TopK": "top_k"}


def _claude_finding(path: str, line: int, param: str) -> Finding:
    return Finding(
        path,
        line,
        rules.CLAUDE_SAMPLING,
        rules.HIGH,
        f'"{param}" is sent to the Claude Messages API. In API version 2026-10-21, which '
        "the Python SDK 2.0.0 and TypeScript SDK 1.0.0 use, a request with temperature, "
        "top_p or top_k returns a 400 error on every model, even at the default value. "
        "On the older API version, Claude 4.7 and later models already return a 400 error "
        "for a non-default value.",
        f'Remove "{param}" and steer the output with the prompt instead.',
    )


def _keep(lx: Lexed, value_at: int) -> bool:
    return not NULL_VALUE.match(lx.code, value_at) and not NULL_VALUE.match(lx.source, value_at)


def check_claude_sampling(lx: Lexed, path: str) -> list:
    if not ANTHROPIC_FILE.search(lx.source):
        return []
    hits = []  # (offset, param)
    spans = []
    if lx.lang == GO:
        for m in GO_CLAUDE_PARAMS.finditer(lx.code):
            spans.append((m.end() - 1, _close_paren(lx.code, m.end() - 1)))
        for a, b in spans:
            for f in GO_FIELD.finditer(lx.code, a, b):
                if lx.prev_char(f.start()) in "{," and _keep(lx, f.end(1)):
                    hits.append((f.start(), GO_NAME[f.group(1)]))
    else:
        for m in CLAUDE_CALL.finditer(lx.code):
            if "threads" in lx.code[max(0, m.start() - 16):m.start()]:
                continue  # OpenAI Assistants: beta.threads.messages.create
            spans.append((m.end() - 1, _close_paren(lx.code, m.end() - 1)))
        rx = PY_KW if lx.lang == PY else JS_KEY
        for a, b in spans:
            for f in rx.finditer(lx.code, a, b):
                if lx.prev_char(f.start()) in "(,{" and _keep(lx, f.end(1)):
                    hits.append((f.start(), f.group(1)))
    # String keys: {"temperature": 0.2} inside a call, or anywhere in a file that
    # posts to api.anthropic.com without an SDK call.
    raw_http = not spans and "api.anthropic.com" in lx.source
    for lit in lx.strings:
        if lit.value not in rules.CLAUDE_SAMPLING_PARAMS or lx.next_char(lit.end) != ":":
            continue
        if lx.prev_char(lit.start) not in "{," or not _keep(lx, lit.end):
            continue
        if raw_http or any(a <= lit.start < b for a, b in spans):
            hits.append((lit.start, lit.value))
    out, seen = [], set()
    for offset, param in sorted(hits):
        line = lx.line_of(offset)
        if (line, param) not in seen:
            seen.add((line, param))
            out.append(_claude_finding(path, line, param))
    return out


# --- LC006 retired OpenAI endpoints -------------------------------------------------

OPENAI_FILE = re.compile(
    r"(?m)^\s*(?:import\s+openai\b|from\s+openai\b)|[\"']openai[\"']|[\"']openai/|openai-go|"
    r"sashabaranov/go-openai|\bAzureOpenAI\b"
)
# (endpoint key, pattern over code with strings blanked)
CALLS = [
    ("assistants", re.compile(r"\bbeta\s*\.\s*(?:assistants|threads)\b")),
    ("assistants", re.compile(r"\bBeta\s*\.\s*(?:Assistants|Threads)\b")),
    ("assistants", re.compile(r"\b(?:CreateAssistant|CreateThread|CreateThreadAndRun|CreateRun)\s*\(")),
    ("evals", re.compile(r"\bevals\s*\.\s*(?:create|update|delete|runs\s*\.\s*create)\s*\(")),
    ("evals", re.compile(r"\bEvals\s*\.\s*(?:New|Update|Delete|Runs\s*\.\s*New)\s*\(")),
    ("audio_translations", re.compile(r"\baudio\s*\.\s*translations\s*\.\s*create\s*\(")),
    ("audio_translations", re.compile(r"\bAudio\s*\.\s*Translations\s*\.\s*New\s*\(|\bCreateTranslation\s*\(")),
    ("videos", re.compile(r"\bvideos\s*\.\s*(?:create|create_and_poll|createAndPoll|remix|retrieve|list|delete|download_content|downloadContent)\s*\(")),
    ("videos", re.compile(r"\bVideos\s*\.\s*(?:New|Get|List|Delete|Remix|DownloadContent)\s*\(")),
]
# (endpoint key, pattern over one string literal's value)
STRINGS = [
    ("prompts", re.compile(r"^pmpt_[A-Za-z0-9]+$")),
    ("realtime_v1", re.compile(r"\brealtime=v1\b")),
    ("assistants_v1", re.compile(r"\bassistants=v1\b")),
    ("assistants", re.compile(r"\bassistants=v2\b")),
]
PATHS = [
    ("assistants", re.compile(r"/v1/(?:assistants|threads)\b")),
    ("prompts", re.compile(r"/v1/prompts\b")),
    ("evals", re.compile(r"/v1/evals\b")),
    ("audio_translations", re.compile(r"/v1/audio/translations\b")),
    ("videos", re.compile(r"/v1/videos\b")),
    ("legacy", re.compile(r"/v1/(?:fine-tunes|edits|engines|answers|classifications)\b")),
]


def _endpoint_finding(path: str, line: int, key: str) -> Finding:
    name, date, repl = rules.OPENAI_ENDPOINTS[key]
    now = today().isoformat()
    if key == "evals":
        verb = "became read-only on" if date < now else "becomes read-only on"
    else:
        verb = "was shut down on" if date < now else "shuts down on"
    msg = f"{name} {verb} {fmt(date)}."
    if date < now and key != "evals":
        msg += " Requests to it fail."
    fix = f"Move to {repl}." if repl else "OpenAI lists no one-to-one replacement; remove this call."
    return Finding(path, line, rules.OPENAI_ENDPOINT, rules.HIGH, msg, fix)


def check_openai_endpoints(lx: Lexed, path: str) -> list:
    hits = []  # (offset, key)
    openai_file = bool(OPENAI_FILE.search(lx.source))
    if openai_file:
        for key, rx in CALLS:
            hits += [(m.start(), key) for m in rx.finditer(lx.code)]
    for lit in lx.strings:
        if lit.docstring or not lit.value:
            continue
        for key, rx in STRINGS:
            if rx.search(lit.value):
                hits.append((lit.start, key))
        if openai_file or "api.openai.com" in lit.value:
            for key, rx in PATHS:
                if rx.search(lit.value):
                    hits.append((lit.start, key))
    out, seen = [], set()
    for offset, key in sorted(hits):
        line = lx.line_of(offset)
        if (line, key) not in seen:
            seen.add((line, key))
            out.append(_endpoint_finding(path, line, key))
    return out
