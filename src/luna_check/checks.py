"""The checks. Each takes a lexed file and returns findings."""

from __future__ import annotations

import re
from dataclasses import dataclass

from . import models, rules
from .lexer import GO, JS, PY, Lexed


@dataclass
class Finding:
    path: str
    line: int
    rule: rules.Rule
    severity: str
    message: str
    fix: str
    low_reason: str = ""  # why a finding is LOW, shown in the short report line
    source: str = ""  # overrides rule.source (LC001: the page that lists this model)
    short: str = ""  # one-line summary for LOW report lines

    def to_dict(self) -> dict:
        return {
            "path": self.path,
            "line": self.line,
            "rule": self.rule.id,
            "title": self.rule.title,
            "severity": self.severity,
            "message": self.message,
            "fix": self.fix,
            "source": self.source or self.rule.source,
            "low_reason": self.low_reason,
        }


# The four OpenAI models that move to gpt-6-luna on Jan 14, 2027. LC002, LC003
# and LC004 are about that migration, so they look only at files naming these.
MODEL_RE = re.compile(
    r"(?<![\w.-])(gpt-4o-mini|gpt-4\.1-mini|gpt-4o|gpt-4\.1)(-\d{4}-\d{2}-\d{2})?(?![\w.-])"
)
PRICE_RE = re.compile(r"(?i)(price|pricing|cost|per_?1[km]\b|per_?million|usd\b|\$\s*\d)")
LUNA_RE = re.compile(r"(?<![\w.-])gpt-6-luna(?![\w.])")


def retiring_ids(s: str):
    """Yield (match, model_id) for every Jan 14, 2027 OpenAI model ID in s."""
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

# Any model name, from any provider. Used only to count how many model names
# sit together in one list or map, so a catalog is not mistaken for a setting.
ANY_MODEL_RE = re.compile(
    r"(?i)^(?:[\w.-]+/)?(?:[a-z0-9-]+\.){0,2}(?:gpt-|chatgpt-|o[1-9](?:-|$)|claude-|gemini-|"
    r"text-embedding-|text-davinci|davinci|babbage|dall-e|whisper-|tts-|codex-|llama|mistral|"
    r"mixtral|command-|deepseek|qwen|grok-|sonar|imagen-|veo-|gemma|nova-|jamba|titan-)[\w.:@-]*$"
)
CATALOG_MIN = 4  # model names in one list/map before it counts as a catalog
CATALOG_NOTE = "model list"


def _innermost_containers(lx: Lexed, parents: dict = None) -> dict:
    """Map each string's start offset to the offset of its innermost open bracket.

    If `parents` is given, it is filled with each bracket's enclosing bracket.
    """
    starts = sorted(lit.start for lit in lx.strings)
    out = {}
    stack = []
    si = 0
    code = lx.code
    for i, ch in enumerate(code):
        while si < len(starts) and starts[si] <= i:
            out[starts[si]] = stack[-1] if stack else None
            si += 1
        if ch in "([{":
            if parents is not None:
                parents[i] = stack[-1] if stack else None
            stack.append(i)
        elif ch in ")]}" and stack:
            stack.pop()
    while si < len(starts):
        out[starts[si]] = stack[-1] if stack else None
        si += 1
    return out


def catalog_containers(lx: Lexed) -> tuple:
    """(catalog bracket offsets, innermost bracket of each string).

    A catalog is a list or map holding CATALOG_MIN or more distinct model names,
    either directly ["a", "b", ...] or as one name per record
    [["a", 0], ["b", 1], ...] / [{"id": "a"}, {"id": "b"}, ...].
    """
    parents = {}
    where = _innermost_containers(lx, parents)
    counts = {}
    for lit in lx.strings:
        c = where.get(lit.start)
        if c is not None and not lit.docstring and ANY_MODEL_RE.match(lit.value):
            counts.setdefault(c, []).append(lit.value)
    catalogs = {c for c, names in counts.items() if len(set(names)) >= CATALOG_MIN}
    records = {}  # parent bracket -> {record bracket: its one model name}
    for c, names in counts.items():
        if len(names) == 1 and parents.get(c) is not None:
            records.setdefault(parents[c], {})[c] = names[0]
    for recs in records.values():
        if len(set(recs.values())) >= CATALOG_MIN:
            catalogs.update(recs)
    return catalogs, where


def check_model_ids(lx: Lexed, path: str, skip_lines: set) -> list:
    out = []
    seen = set()  # one finding per model per line
    catalogs, where = catalog_containers(lx)
    context = models.platforms_in(lx.source)
    for lit in lx.strings:
        if lit.docstring or not lit.value:
            continue
        if re.search(r"\s", lit.value):
            continue  # prose, log text, prompts, SQL: not a model ID setting
        if lx.prev_char(lit.start) in "{," and lx.next_char(lit.end) == ":" and lx.prev_char(lit.start):
            continue  # a mapping key, as in a price or context-size table
        if _is_name_test(lx, lit):
            continue  # startswith("gpt-4"), "gpt-4" in name: a name test, not a model in use
        in_catalog = where.get(lit.start) in catalogs
        base = _value_offset(lx, lit)
        for start, model in models.catalog().find(lit.value):
            line = lx.line_of(base + start)
            if line in skip_lines or PRICE_RE.search(lx.line_text(line)) or (line, model) in seen:
                continue
            rep = models.describe(model, context)
            if rep is None:
                continue
            seen.add((line, model))
            out.append(model_finding(path, line, rep, in_catalog))
    return out


NAME_TEST_CALL = re.compile(
    r"(?:startswith|startsWith|HasPrefix|hasPrefix|has_prefix|endswith|endsWith|HasSuffix|"
    r"hasSuffix|includes|Contains|contains|indexOf|index|find|TrimPrefix|removeprefix)"
    r"\s*\(\s*(?:[^(),]*,\s*)?[(\[]?\s*(?:[^()]*,\s*)?$"
)


def _is_name_test(lx: Lexed, lit) -> bool:
    """The string is a prefix/substring pattern checked against a model name."""
    line_start = lx.code.rfind("\n", 0, lit.start) + 1
    if NAME_TEST_CALL.search(lx.code[line_start:lit.start]):
        return True
    after = lx.code[lit.end:lit.end + 8]
    return lx.lang == PY and re.match(r"\s*(?:not\s+)?in\b", after) is not None and \
        lx.prev_char(lit.start) not in "([{,"


def model_finding(path: str, line: int, rep, in_catalog: bool) -> Finding:
    f = Finding(path, line, rules.MODEL_ID, rep.severity, rep.message, rep.fix,
                rep.low_reason, rep.source, rep.short)
    if in_catalog and f.severity == rules.HIGH:
        # A list of many model names (a catalog or allow-list), not the model
        # this code sends. Worth cleaning up, but not urgent.
        f.severity = rules.LOW
        f.low_reason = CATALOG_NOTE
        f.message += " (One entry in a list of many model names, so lower priority.)"
        f.fix = "Remove it from the list" + (
            f', or add "{rep.replacement}" if the list is missing it.' if rep.replacement else ".")
    return f


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
        "The gpt-6-luna model page says that on Chat Completions it accepts function "
        'calling only when reasoning_effort is "none".',
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


# --- LC003 sampling parameters with reasoning on ------------------------------

SAMPLING_ALT = "|".join(rules.SAMPLING_PARAMS)
PY_KWARG = re.compile(rf"\b({SAMPLING_ALT})\s*=(?!=)")
JS_KEY = re.compile(rf"\b({SAMPLING_ALT})\s*:")
GO_FIELD = re.compile(r"\b(Temperature|TopP|Logprobs|LogProbs|TopLogprobs|TopLogProbs)\s*:")
GO_ASSIGN = re.compile(r"\.(Temperature|TopP|Logprobs|LogProbs|TopLogprobs|TopLogProbs)\s*=(?!=)")
NULL_VALUE = re.compile(r"\s*[:=]\s*(None|null|undefined|nil)\b")
EFFORT_CODE = re.compile(r"\b(?:reasoning_effort|reasoningEffort|ReasoningEffort|effort)\b")
EFFORT_KEYS = ("reasoning_effort", "reasoningEffort", "effort")
GO_PARAM = {"Temperature": "temperature", "TopP": "top_p", "Logprobs": "logprobs",
            "LogProbs": "logprobs", "TopLogprobs": "top_logprobs", "TopLogProbs": "top_logprobs"}

NONE, OTHER, UNKNOWN = "none", "other", "unknown"


def _effort_states(lx: Lexed, start: int, end: int) -> set:
    """How reasoning effort is set between start and end.

    For each mention of reasoning_effort (or an "effort" key), look at the value
    right after it: the string "none" -> NONE, another string -> OTHER,
    anything else (a variable, a function call) -> UNKNOWN.
    """
    marks = [m.end() for m in EFFORT_CODE.finditer(lx.code, start, end)]
    marks += [lit.end for lit in lx.strings if start <= lit.start < end and lit.value in EFFORT_KEYS]
    states = set()
    for pos in marks:
        value = None
        for lit in lx.strings:
            if lit.start >= pos:
                if re.fullmatch(r"[\s:=]*", lx.code[pos:lit.start]):
                    value = lit.value
                break
        if value is None:
            states.add(UNKNOWN)
        else:
            states.add(NONE if value == "none" else OTHER)
    return states


def _enclosing_spans(code: str, offset: int, levels: int = 2) -> list:
    spans = []
    depth = 0
    k = offset - 1
    while k >= 0 and len(spans) < levels:
        ch = code[k]
        if ch in ")]}":
            depth += 1
        elif ch in "([{":
            if depth == 0:
                spans.append((k, _close_paren(code, k) + 1))
            else:
                depth -= 1
        k -= 1
    return spans


def _sampling_finding(path: str, line: int, param: str) -> Finding:
    return Finding(
        path,
        line,
        rules.SAMPLING,
        rules.HIGH,
        f'"{param}" is sent and reasoning effort is not "none" (gpt-6-luna defaults '
        'to "medium"). OpenAI\'s Using GPT-6 guide says to drop temperature, top_p '
        "and top_logprobs in that case, and also logprobs on Chat Completions.",
        f'Remove "{param}" from this request when moving to gpt-6-luna.',
    )


def check_sampling(lx: Lexed, path: str) -> list:
    hits = []  # (offset, param)

    def keep(offset: int, value_at: int) -> bool:
        return not NULL_VALUE.match(lx.code, value_at) and not NULL_VALUE.match(lx.source, value_at)

    if lx.lang == PY:
        for m in PY_KWARG.finditer(lx.code):
            if lx.prev_char(m.start()) in "(," and keep(m.start(), m.end(1)):
                hits.append((m.start(), m.group(1)))
    elif lx.lang == JS:
        for m in JS_KEY.finditer(lx.code):
            if lx.prev_char(m.start()) in "{," and keep(m.start(), m.end(1)):
                hits.append((m.start(), m.group(1)))
    else:
        for rx in (GO_FIELD, GO_ASSIGN):
            for m in rx.finditer(lx.code):
                if (rx is GO_ASSIGN or lx.prev_char(m.start()) in "{,") and keep(m.start(), m.end(1)):
                    hits.append((m.start(), GO_PARAM[m.group(1)]))
    for lit in lx.strings:
        if (lit.value in rules.SAMPLING_PARAMS and lx.next_char(lit.end) == ":"
                and lx.prev_char(lit.start) in "{," and keep(lit.start, lit.end)):
            hits.append((lit.start, lit.value))

    out = []
    seen = set()
    file_states = _effort_states(lx, 0, len(lx.code)) if lx.lang == GO else None
    for offset, param in sorted(hits):
        if lx.lang == GO:
            # Go request structs are often built far from where fields are set.
            states = file_states
        else:
            states = set()
            for a, b in _enclosing_spans(lx.code, offset):
                states |= _effort_states(lx, a, b)
        if NONE in states or UNKNOWN in states:
            continue  # effort is "none", or set from a variable we cannot see
        line = lx.line_of(offset)
        if (line, param) not in seen:
            seen.add((line, param))
            out.append(_sampling_finding(path, line, param))
    return out


def run_all(lx: Lexed, path: str, strict: bool = False) -> list:
    # `strict` is kept for compatibility. Since 0.2.0 every rule runs by default.
    from .api_checks import check_claude_sampling, check_openai_endpoints

    relevant = is_relevant(lx)
    tiktoken_lines = {lx.line_of(m.start()) for m in TIKTOKEN_CALL[lx.lang].finditer(lx.code)}
    # A model name passed to a tokenizer lookup is not an API call, so LC001
    # skips those lines; LC002 reports the ones that break.
    findings = check_tiktoken(lx, path) if (relevant or tiktoken_lines) else []
    findings += check_model_ids(lx, path, tiktoken_lines)
    if relevant:
        findings += check_chat_tools(lx, path)
        findings += check_sampling(lx, path)
    findings += check_claude_sampling(lx, path)
    findings += check_openai_endpoints(lx, path)
    return findings
