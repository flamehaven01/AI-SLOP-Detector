"""v3.10 P3-2: init preview hotspots are capped per function, grouped by name.

Measured: in financial-services one function copied into three files
(_check_terminal_value_proportion) took all three hotspot slots, so the
preview listed one name three times and no other function. The cap counted
file entries, not functions.

Contract: at most three distinct function names; every file of a kept name
keeps its own evidence (path, complexity, lines); the preview lists each name
once with its files under it. Nothing is written to the config.
"""

from __future__ import annotations

from slop_detector.cli_init import _render_init_preview, _suggest_domain_overrides


def _candidate(name, path, complexity=22, lines=40):
    return {
        "function_name": name,
        "file_path": path,
        "complexity": complexity,
        "logic_lines": lines,
    }


SIGNALS = {
    "domain": {"path": "general"},
    "python_complexity_candidates": [
        _candidate("_check", "a/validate.py"),
        _candidate("_check", "b/validate.py"),
        _candidate("_check", "c/validate.py", complexity=21),
        _candidate("build", "build.py", complexity=18),
        _candidate("parse", "parse.py", complexity=16),
        _candidate("render", "render.py", complexity=15),
    ],
}


def test_cap_counts_functions_and_keeps_every_file():
    suggestions = _suggest_domain_overrides(SIGNALS)
    rows = [(s["function_pattern"], s["evidence"]["file_path"]) for s in suggestions]
    assert rows == [
        ("_check", "a/validate.py"),
        ("_check", "b/validate.py"),
        ("_check", "c/validate.py"),
        ("build", "build.py"),
        ("parse", "parse.py"),
    ]


def test_preview_lists_a_name_once_with_its_files():
    overrides = _suggest_domain_overrides(SIGNALS)
    text = _render_init_preview(
        "python", "general", SIGNALS, {"god_function_domain_overrides": overrides}
    )
    block = text.split("Complexity hotspots to review (not written to config):")[1]
    assert block.count("_check") == 1
    for path, complexity in (("a/validate.py", 22), ("b/validate.py", 22), ("c/validate.py", 21)):
        assert f"{path} (complexity {complexity}, lines 40)" in block
    assert "build" in block and "parse" in block and "render" not in block
