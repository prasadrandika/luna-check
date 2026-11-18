"""A small lexer for Python, JavaScript/TypeScript and Go.

It does not parse the language. It only finds comments and string literals so
the checks can ignore comments and docstrings and look at real code.

`Lexed.code` is the source with every comment and every string's contents
replaced by spaces. Newlines are kept, so offsets and line numbers match the
original file.
"""

from __future__ import annotations

import bisect
import re
from dataclasses import dataclass, field

PY = "python"
JS = "javascript"
GO = "go"

EXTENSIONS = {
    ".py": PY,
    ".js": JS,
    ".jsx": JS,
    ".mjs": JS,
    ".cjs": JS,
    ".ts": JS,
    ".tsx": JS,
    ".mts": JS,
    ".cts": JS,
    ".go": GO,
}

_PY_PREFIX = re.compile(r"(?i)(?:rb|br|fr|rf|r|b|f|u)?$")
_REGEX_BEFORE = set("(,=:[!&|?{};+-*%<>~^")


@dataclass
class StringLit:
    value: str  # contents without quotes
    start: int  # offset of the opening quote (or prefix)
    end: int  # offset just after the closing quote
    docstring: bool = False


@dataclass
class Lexed:
    source: str
    lang: str
    code: str
    strings: list = field(default_factory=list)
    _newlines: list = field(default_factory=list)

    def line_of(self, offset: int) -> int:
        return bisect.bisect_right(self._newlines, offset - 1) + 1

    def prev_char(self, offset: int) -> str:
        """Last non-space character of code before offset ('' at start)."""
        i = offset - 1
        while i >= 0 and self.code[i] in " \t\r\n":
            i -= 1
        return self.code[i] if i >= 0 else ""

    def next_char(self, offset: int) -> str:
        i = offset
        n = len(self.code)
        while i < n and self.code[i] in " \t\r\n":
            i += 1
        return self.code[i] if i < n else ""

    def line_text(self, line: int) -> str:
        lines = self.source.split("\n")
        return lines[line - 1] if 0 < line <= len(lines) else ""


def _blank(chars: list, start: int, end: int) -> None:
    for k in range(start, end):
        if chars[k] != "\n":
            chars[k] = " "


def lex(source: str, lang: str) -> Lexed:
    source = source.replace("\r\n", "\n").replace("\r", "\n")
    chars = list(source)
    strings = []
    n = len(source)
    i = 0
    depth = 0  # bracket depth, used for Python docstring detection

    while i < n:
        c = source[i]

        # --- comments -------------------------------------------------
        if lang == PY and c == "#":
            j = source.find("\n", i)
            j = n if j == -1 else j
            _blank(chars, i, j)
            i = j
            continue
        if lang in (JS, GO) and source.startswith("//", i):
            j = source.find("\n", i)
            j = n if j == -1 else j
            _blank(chars, i, j)
            i = j
            continue
        if lang in (JS, GO) and source.startswith("/*", i):
            j = source.find("*/", i + 2)
            j = n if j == -1 else j + 2
            _blank(chars, i, j)
            i = j
            continue

        # --- JS regex literal -----------------------------------------
        if lang == JS and c == "/":
            k = i - 1
            while k >= 0 and chars[k] in " \t\r\n":
                k -= 1
            prev = chars[k] if k >= 0 else ""
            word = re.search(r"[A-Za-z_$][\w$]*$", "".join(chars[max(0, k - 10) : k + 1]))
            if prev == "" or prev in _REGEX_BEFORE or (word and word.group() in ("return", "typeof", "case", "in", "of")):
                j = i + 1
                in_class = False
                while j < n and source[j] != "\n":
                    ch = source[j]
                    if ch == "\\":
                        j += 2
                        continue
                    if ch == "[":
                        in_class = True
                    elif ch == "]":
                        in_class = False
                    elif ch == "/" and not in_class:
                        break
                    j += 1
                if j < n and source[j] == "/":
                    _blank(chars, i + 1, j)
                    i = j + 1
                    continue

        # --- strings --------------------------------------------------
        quote = None
        start = i
        if lang == PY and c in "\"'":
            # Include a prefix like r, f, rb that was already copied as code.
            k = i
            while k > 0 and source[k - 1].isalpha() and i - k < 2:
                k -= 1
            if k < i and _PY_PREFIX.match(source[k:i]) and (k == 0 or not (source[k - 1].isalnum() or source[k - 1] == "_")):
                start = k
            quote = source[i : i + 3] if source[i : i + 3] in ('"""', "'''") else c
        elif lang == JS and c in "\"'`":
            quote = c
        elif lang == GO and c in "\"'`":
            quote = c

        if quote:
            raw = (lang == GO and quote == "`")
            j = i + len(quote)
            while j < n:
                if not raw and source[j] == "\\":
                    j += 2
                    continue
                if source.startswith(quote, j):
                    break
                if source[j] == "\n" and len(quote) == 1 and quote != "`":
                    break  # unterminated single-line string
                j += 1
            end = min(n, j + len(quote))
            value = source[i + len(quote) : j]
            doc = False
            if lang == PY and len(quote) == 3 and depth == 0 and _at_line_start(chars, start):
                rest = source[end : (source.find("\n", end) if source.find("\n", end) != -1 else n)]
                if rest.split("#", 1)[0].strip() == "":
                    doc = True
            strings.append(StringLit(value, start, end, doc))
            if doc:
                _blank(chars, start, end)
            else:
                _blank(chars, i + len(quote), j)
            i = end
            continue

        if c in "([{":
            depth += 1
        elif c in ")]}":
            depth = max(0, depth - 1)
        i += 1

    newlines = [k for k, ch in enumerate(source) if ch == "\n"]
    return Lexed(source, lang, "".join(chars), strings, newlines)


def _at_line_start(chars: list, offset: int) -> bool:
    k = offset - 1
    while k >= 0 and chars[k] in " \t":
        k -= 1
    return k < 0 or chars[k] == "\n"
