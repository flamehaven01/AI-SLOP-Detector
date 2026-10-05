"""Claims and rules that could never apply, removed without changing behavior.

- LDR `EMPTY_PATTERNS` held comment regexes (`# TODO`, `# FIXME`,
  `# placeholder`, `# implementation details`), but LDR skips every line that
  starts with `#` before the patterns are tried, so they never matched.
- The JS/TS analyzer docstring listed `ts_missing_return_type`, which no code
  emits.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

from slop_detector.config import Config
from slop_detector.metrics.ldr import LDRCalculator

SRC = (
    "def a():\n"
    "    # TODO: write this\n"
    "    # FIXME later\n"
    "    # placeholder\n"
    "    # implementation details\n"
    "    x = 1  # TODO inline\n"
    "    return x\n"
    "\n"
    "\n"
    "def b():\n"
    "    pass\n"
    "\n"
    "\n"
    "def c():\n"
    "    raise NotImplementedError\n"
    "\n"
    "\n"
    "def d(v):\n"
    "    if v:\n"
    "        pass\n"
    "    ...\n"
    "    return v\n"
)


def test_every_empty_pattern_can_reach_a_line():
    """A pattern that needs a leading `#` targets lines LDR has already skipped."""
    unreachable = [p for p in LDRCalculator.EMPTY_PATTERNS if re.match(r"\^\\s\*#", p)]
    assert unreachable == []


def test_ldr_result_is_unchanged():
    """Measured on this corpus before the comment regexes were removed."""
    result = LDRCalculator(Config()).calculate("m.py", SRC, ast.parse(SRC))
    assert (result.total_lines, result.logic_lines, result.empty_lines) == (12, 7, 5)
    assert round(result.ldr_score, 6) == 0.583333
    assert result.grade == "B"


def test_remaining_empty_patterns_still_apply():
    calculator = LDRCalculator(Config())
    for line in ("pass", "...", "raise NotImplementedError", "raise NotImplementedError('x')"):
        assert any(p.match(line) for p in calculator.compiled_patterns), line
    for line in ("x = 1", "return None", "# TODO"):
        assert not any(p.match(line) for p in calculator.compiled_patterns), line


def test_js_analyzer_docstring_lists_only_emitted_patterns():
    import slop_detector.languages.js_analyzer as js_analyzer

    source = Path(js_analyzer.__file__).read_text(encoding="utf-8")
    docstring = ast.get_docstring(ast.parse(source)) or ""
    listed = re.findall(r"^\s*((?:js|ts)_[a-z_]+)\s*:", docstring, flags=re.M)
    code = source.replace(docstring, "")
    assert listed, "no pattern list found in the docstring"
    missing = [pattern_id for pattern_id in listed if f'"{pattern_id}"' not in code]
    assert missing == []
