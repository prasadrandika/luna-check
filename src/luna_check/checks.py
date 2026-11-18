"""The four checks. Each takes a lexed file and returns findings."""

from __future__ import annotations

import re
from dataclasses import dataclass

from . import rules
from .lexer import GO, JS, PY, Lexed


@dataclass
class Finding:
    path: str
    line: int
    rule: rules.Rule
    severity: str
    message: str
    fix: str

    def to_dict(self) -> dict:
        return {
            "path": self.path,
            "line": self.line,
            "rule": self.rule.id,
            "title": self.rule.title,
            "severity": self.severity,
            "message": self.message,
            "fix": self.fix,
            "source": self.rule.source,
        }


# A retiring alias, optionally followed by a date. Not preceded or followed by
# characters that would make it a different model, such as gpt-4o-mini-search-preview.
MODEL_RE = re.compile(
    r"(?<![\w.-])(gpt-4o-mini|gpt-4\.1-mini|gpt-4o|gpt-4\.1)(-\d{4}-\d{2}-\d{2})?(?![\w.-])"
)
PRICE_RE = re.compile(r"(?i)(price|pricing|cost|per_?1[km]\b|per_?million|usd\b|\$\s*\d)")
LUNA_RE = re.compile(r"(?<![\w.-])gpt-6-luna(?![\w.])")


def retiring_ids(s: str):
    """Yield (match, model_id) for every retiring model ID in s."""
    for m in MODEL_RE.finditer(s):
        full = m.group(0)
        if m.group(2) and full not in rules.DATED_IDS:
            continue  # a different snapshot, not part of the Jan 14, 2027 shutdown
        yield m, full


def _value_offset(lx: Lexed, lit) -> int:
    """Offset in the source where a string's contents start."""
    idx = lx.source.find(lit.value, lit.start) if lit.value else -1
    return idx if idx != -1 else lit.start


def is_relevant(lx: Lexed) -> bool:
    """The file names a retiring model or gpt-6-luna in code (not comments)."""
    for lit in lx.strings:
        if lit.docstring:
            continue
        if LUNA_RE.search(lit.value) or any(True for _ in retiring_ids(lit.value)):
            return True
    return False


# --- LC001 ------------------------------------------------------------------

def check_model_ids(lx: Lexed, path: str, skip_lines: set) -> list:
    out = []
    seen = set()  # one finding per model per line
    for lit in lx.strings:
        if lit.docstring or not lit.value:
            continue
        if re.search(r"\s", lit.value):
            continue  # prose, log text, prompts, SQL: not a model ID setting
        if lx.prev_char(lit.start) in "{," and lx.next_char(lit.end) == ":" and lx.prev_char(lit.start):
            continue  # a mapping key, as in a price or context-size table
        base = _value_offset(lx, lit)
        for m, model in retiring_ids(lit.value):
            line = lx.line_of(base + m.start())
            if line in skip_lines or PRICE_RE.search(lx.line_text(line)) or (line, model) in seen:
                continue
            seen.add((line, model))
            out.append(
                Finding(
                    path,
                    line,
                    rules.MODEL_ID,
                    rules.HIGH,
                    rules.model_message(model),
                    f'Use "{rules.REPLACEMENT}" (or read the model name from config).',
                )
            )
    return out


# --- LC002 ------------------------------------------------------------------

TIKTOKEN_CALL = {
    PY: re.compile(r"\bencoding_for_model\s*\("),
    JS: re.compile(r"\b(?:encoding_for_model|encodingForModel)\s*\("),
    GO: re.compile(r"\bEncodingForModel\s*\("),
}
FALLBACK_RE = re.compile(r"\b(?:get_encoding|getEncoding|GetEncoding)\s*\(")
FALLBACK_WINDOW = 8  # lines after the call in which a fallback counts


def _first_arg_string(lx: Lexed, open_paren: int):
    for lit in lx.strings:
        if lit.start >= open_paren:
            between = lx.code[open_paren + 1 : lit.start]
            return lit if between.strip() == "" else None
    return None


def check_tiktoken(lx: Lexed, path: str) -> list:
    out = []
    for m in TIKTOKEN_CALL[lx.lang].finditer(lx.code):
        line = lx.line_of(m.start())
        lit = _first_arg_string(lx, m.end() - 1)
        if lit is not None:
            ids = [mid for _, mid in retiring_ids(lit.value)]
            if not ids and not LUNA_RE.search(lit.value):
                continue  # a literal model that is not part of this migration
        window = lx.code.split("\n")[line - 1 : line - 1 + FALLBACK_WINDOW]
        if FALLBACK_RE.search("\n".join(window)):
            continue  # already falls back to an explicit encoding
        arg = f'"{lit.value}"' if lit is not None else "the model name"
        out.append(
            Finding(
                path,
                line,
                rules.TIKTOKEN,
                rules.HIGH,
                f"Called with {arg}. tiktoken has no entry for "
                f'"{rules.REPLACEMENT}", so after the switch this raises KeyError '
                "(checked with tiktoken 0.7.0 and 0.14.0).",
                f"Catch the error and fall back to get_encoding(\"{rules.OLD_ENCODING}\"), "
                "the encoding tiktoken uses for gpt-4o, gpt-4o-mini, gpt-4.1 and gpt-4.1-mini.",
            )
        )
    return out


# --- LC004 ------------------------------------------------------------------

CHAT_CALL = re.compile(r"\bchat\s*\.\s*completions\s*\.\s*(?:create|parse|stream)\s*\(")
GO_CHAT_CALL = re.compile(r"\b(?:Chat\.Completions\.New|CreateChatCompletion(?:Stream)?)\s*\(")
PY_TOOLS = re.compile(r"\b(?:tools|functions)\s*=(?!=)")
JS_TOOLS = re.compile(r"\b(?:tools|functions)\s*[:,}]")
EFFORT_RE = re.compile(r"\b(?:reasoning_effort|reasoningEffort|ReasoningEffort)\b")


def _close_paren(code: str, open_idx: int) -> int:
    depth = 0
    for k in range(open_idx, len(code)):
        ch = code[k]
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
            if depth == 0:
                return k
    return len(code)


def _has_effort(lx: Lexed, start: int, end: int) -> bool:
    if EFFORT_RE.search(lx.code[start:end]):
        return True
    return any(
        start <= lit.start < end and EFFORT_RE.search(lit.value) for lit in lx.strings
    )


def _tools_finding(path: str, line: int) -> Finding:
    return Finding(
        path,
        line,
        rules.CHAT_TOOLS,
        rules.HIGH,
        "Function tools are sent to /chat/completions with no reasoning_effort. "
        'gpt-6-luna "supports function calling only with `reasoning_effort` set to `none`" '
        "on Chat Completions.",
        'Send reasoning_effort "none" with gpt-6-luna, or move to the Responses API.',
    )


def check_chat_tools(lx: Lexed, path: str) -> list:
    out = []
    if lx.lang in (PY, JS):
        tools_re = PY_TOOLS if lx.lang == PY else JS_TOOLS
        for m in CHAT_CALL.finditer(lx.code):
            close = _close_paren(lx.code, m.end() - 1)
            args = lx.code[m.end() : close]
            if tools_re.search(args) and not _has_effort(lx, m.end(), close):
                out.append(_tools_finding(path, lx.line_of(m.start())))
        return out

    # Go: raw HTTP clients build the request in a struct, so look at the file.
    if _has_effort(lx, 0, len(lx.code)):
        return out
    has_tools = re.search(r"\bTools\s*:", lx.code) or any(
        re.search(r'json:"tools[,"]', lit.value) or (lit.value == "tools" and lx.next_char(lit.end) == ":")
        for lit in lx.strings
    )
    if not has_tools:
        return out
    for lit in lx.strings:
        if lit.value.rstrip("/").endswith("/chat/completions"):
            out.append(_tools_finding(path, lx.line_of(lit.start)))
    for m in GO_CHAT_CALL.finditer(lx.code):
        out.append(_tools_finding(path, lx.line_of(m.start())))
    return out


# --- LC003 (only with --strict) --------------------------------------------

SAMPLING_ALT = "|".join(rules.SAMPLING_PARAMS)
PY_KWARG = re.compile(rf"\b({SAMPLING_ALT})\s*=(?!=)")
JS_KEY = re.compile(rf"\b({SAMPLING_ALT})\s*:")
GO_FIELD = re.compile(r"\b(Temperature|TopP|Logprobs|LogProbs|TopLogprobs|TopLogProbs)\s*:")
GO_TAG = re.compile(rf'json:"({SAMPLING_ALT})[,"]')


def _sampling_finding(path: str, line: int, param: str) -> Finding:
    return Finding(
        path,
        line,
        rules.SAMPLING,
        rules.UNCONFIRMED,
        f'"{param}" is set. OpenAI\'s GPT-6.2 migration guide says to omit '
        "temperature, top_p, logprobs and top_logprobs on Chat Completions. "
        "Not confirmed for gpt-6-luna: its model page does not say.",
        "Test this request against gpt-6-luna before shipping.",
    )


def check_sampling(lx: Lexed, path: str) -> list:
    out = []
    seen = set()

    def add(offset: int, param: str) -> None:
        line = lx.line_of(offset)
        if (line, param) not in seen:
            seen.add((line, param))
            out.append(_sampling_finding(path, line, param))

    if lx.lang == PY:
        for m in PY_KWARG.finditer(lx.code):
            if lx.prev_char(m.start()) in "(,":
                add(m.start(), m.group(1))
    elif lx.lang == JS:
        for m in JS_KEY.finditer(lx.code):
            if lx.prev_char(m.start()) in "{,":
                add(m.start(), m.group(1))
    else:
        for m in GO_FIELD.finditer(lx.code):
            if lx.prev_char(m.start()) in "{,":
                add(m.start(), m.group(1))
    for lit in lx.strings:
        if lit.value in rules.SAMPLING_PARAMS and lx.next_char(lit.end) == ":" and lx.prev_char(lit.start) in "{,":
            add(lit.start, lit.value)
        if lx.lang == GO:
            t = GO_TAG.search(lit.value)
            if t:
                add(lit.start, t.group(1))
    return out


def run_all(lx: Lexed, path: str, strict: bool) -> list:
    if not is_relevant(lx) and not TIKTOKEN_CALL[lx.lang].search(lx.code):
        return []
    tiktoken = check_tiktoken(lx, path)
    findings = tiktoken + check_model_ids(lx, path, {f.line for f in tiktoken})
    if is_relevant(lx):
        findings += check_chat_tools(lx, path)
        if strict:
            findings += check_sampling(lx, path)
    return findings
