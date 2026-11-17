"""The code of a JS/TS or Go source, for regex rules that judge code.

`code_lines` returns the source's lines with the text of string literals and
comments replaced by spaces of the same length, so a rule's regex sees only
code and a match keeps its line and column. Line breaks are kept, so the
view has as many lines as `content.splitlines()`.

Read as text (not code):
  js  "..." and '...' strings, `...` templates (the ${...} inside one is
      code), /.../ regular expression literals, // and /* */ comments
  go  "..." strings, `...` raw strings, '...' runes, // and /* */ comments

`views` also returns the comment view: only the text of comments kept, code
and string text blanked, for rules and line counts about comments (a TODO
marker, a comment line) that must not read text inside a string.
"""

from __future__ import annotations

from typing import List, Optional, Tuple

# Characters str.splitlines() breaks on: kept so the view splits the same way.
_BREAKS = frozenset("\n\r\x0b\x0c\x1c\x1d\x1e") | {chr(0x85), chr(0x2028), chr(0x2029)}
# After one of these (or at the start), a / starts a regular expression literal.
_REGEX_AFTER = frozenset("(,=:[!&|?{};+-*%<>~^")
_REGEX_KEYWORDS = frozenset(
    {
        "return",
        "typeof",
        "case",
        "do",
        "else",
        "in",
        "of",
        "new",
        "delete",
        "void",
        "throw",
        "yield",
        "await",
    }
)


def code_lines(content: str, dialect: str) -> List[str]:
    """The lines of `content` with string and comment text blanked (see module)."""
    return views(content, dialect)[0]


def views(content: str, dialect: str) -> Tuple[List[str], List[str], List[bool]]:
    """(code view, comment view, in a comment) of `content`, by line: the last
    says whether the line ends inside a block comment (a blank line within one
    is part of the comment)."""
    scanner = _Scanner(content, dialect)
    code = scanner.run()
    comments = "".join(
        c if scanner.in_comment[k] or c in _BREAKS else " " for k, c in enumerate(content)
    )
    ends_in_comment, offset = [], 0
    for line in content.splitlines(keepends=True):
        offset += len(line)
        ends_in_comment.append(line[-1:] in _BREAKS and scanner.in_comment[offset - 1])
    return code.splitlines(), comments.splitlines(), ends_in_comment


class _Scanner:
    def __init__(self, content: str, dialect: str) -> None:
        self.src = content
        self.out = list(content)
        self.js = dialect == "js"
        self.templates: List[int] = []  # open ${ in a JS template: brace depth inside it
        self.prev = ""  # the last code character that is not a space ("a" after a word)
        self.word = ""  # the last word, when prev is "a"
        self.in_comment = [False] * len(content)  # characters of a comment

    def blank(self, start: int, end: int) -> None:
        for k in range(start, min(end, len(self.out))):
            if self.out[k] not in _BREAKS:
                self.out[k] = " "

    def comment(self, start: int, end: int) -> None:
        self.blank(start, end)
        for k in range(start, min(end, len(self.in_comment))):
            self.in_comment[k] = True

    def run(self) -> str:
        i, n = 0, len(self.src)
        while i < n:
            i = self.step(i)
        return "".join(self.out)

    def step(self, i: int) -> int:
        src, c = self.src, self.src[i]
        if src.startswith("//", i):
            end = src.find("\n", i)
            end = len(src) if end < 0 else end
            self.comment(i, end)
            return end
        if src.startswith("/*", i):
            end = src.find("*/", i + 2)
            end = len(src) if end < 0 else end + 2
            self.comment(i, end)
            return end
        if c in "\"'":
            return self.quoted(i, c)
        if c == "`":
            return self.template(i + 1) if self.js else self.raw(i)
        if self.js:
            end = self.js_step(i, c)
            if end is not None:
                return end
        return self.code(i)

    def js_step(self, i: int, c: str) -> Optional[int]:
        """A regex literal, or the } closing a template's ${...}; None otherwise
        (the braces inside a ${...} are counted on the way)."""
        if c == "/" and self.regex_allowed():
            end = self.regex_end(i)
            if end is not None:
                self.blank(i + 1, end)
                self.prev, self.word = "a", ""
                return end + 1
        if self.templates and c == "{":
            self.templates[-1] += 1
        elif self.templates and c == "}":
            if self.templates[-1] == 0:
                self.templates.pop()
                return self.template(i + 1)
            self.templates[-1] -= 1
        return None

    def code(self, i: int) -> int:
        c = self.src[i]
        if c.isalnum() or c in "_$":
            j = i
            while j < len(self.src) and (self.src[j].isalnum() or self.src[j] in "_$"):
                j += 1
            self.prev, self.word = "a", self.src[i:j]
            return j
        if not c.isspace():
            self.prev, self.word = c, ""
        return i + 1

    def quoted(self, i: int, quote: str) -> int:
        """A "..." or '...' literal (one line); its text is blanked."""
        j = i + 1
        while j < len(self.src) and self.src[j] != quote and self.src[j] not in _BREAKS:
            j += 2 if self.src[j] == "\\" else 1
        self.blank(i + 1, j)
        self.prev, self.word = "a", ""
        return j + 1 if j < len(self.src) and self.src[j] == quote else j

    def raw(self, i: int) -> int:
        """A Go `...` raw string (any lines, no escapes)."""
        end = self.src.find("`", i + 1)
        end = len(self.src) if end < 0 else end
        self.blank(i + 1, end)
        self.prev, self.word = "a", ""
        return end + 1

    def template(self, j: int) -> int:
        """JS template text from j up to its closing ` or the next ${."""
        while j < len(self.src):
            if self.src[j] == "\\":
                self.blank(j, j + 2)
                j += 2
            elif self.src[j] == "`":
                self.prev, self.word = "a", ""
                return j + 1
            elif self.src.startswith("${", j):
                self.templates.append(0)
                self.prev, self.word = "(", ""
                return j + 2
            else:
                self.blank(j, j + 1)
                j += 1
        return j

    def regex_allowed(self) -> bool:
        return self.prev == "" or self.prev in _REGEX_AFTER or self.word in _REGEX_KEYWORDS

    def regex_end(self, i: int) -> Optional[int]:
        """Index of the / closing a regex literal opened at i, or None (division)."""
        j, in_class = i + 1, False
        while j < len(self.src) and self.src[j] not in _BREAKS:
            c = self.src[j]
            if c == "\\":
                j += 2
                continue
            if c == "[":
                in_class = True
            elif c == "]":
                in_class = False
            elif c == "/" and not in_class:
                return j
            j += 1
        return None
