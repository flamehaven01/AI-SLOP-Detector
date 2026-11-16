"""Advice must rest on something that was measured.

Inflation and DDC exist for Python files only. The project values are averages
over the Python files that have them; with no such file the average of nothing
was 0.0, and a project of Rust and JS/TS files was told "Top concern:
Dependency Usage Ratio (DDC) = 0.00%" and to run `sweep unused-deps`, a
command that reads Python imports.

- a metric no file has reads N/A and is never a concern;
- the sweep commands (they read Python) are advised only where a Python file
  was analyzed;
- a Python project with a real DDC problem is still told so (positive control).
"""

from __future__ import annotations

from pathlib import Path

from slop_detector.core import SlopDetector
from slop_detector.renderer_glossary import next_steps, project_metric_rows

# A stub call and a debug print: a flagged (suspicious) file, not only findings.
RUST = "pub fn parse(input: &str) -> u8 {\n    dbg!(input);\n    todo!()\n}\n"
JSX = "var count = 0;\n\nexport function App(props) {\n  console.log(props);\n  return count;\n}\n"
# One import of three is never used: a measured dependency usage ratio of 2/3,
# in an otherwise clean file, so DDC is the only concern.
PY_UNUSED_IMPORTS = (
    "import json\nimport os\nimport csv\n\n\n"
    "def load(path):\n"
    '    with open(os.path.abspath(path), encoding="utf-8") as handle:\n'
    "        return json.load(handle)\n\n\n"
    "def total(values):\n    result = 0\n    for value in values:\n        result += value\n"
    "    return result\n"
)


def _scan(root: Path, files: dict):
    for name, text in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return SlopDetector(read_only=True).analyze_project(str(root))


def _rows(result) -> dict:
    return {row["label"]: row for row in project_metric_rows(result)}


def test_python_project_with_unused_imports_is_still_told_about_ddc(tmp_path):
    """Positive control: the DDC concern and its sweep survive the fix."""
    result = _scan(tmp_path, {"pkg/calc.py": PY_UNUSED_IMPORTS})
    ddc = _rows(result)["Dependency Usage Ratio (DDC)"]
    assert ddc["health"] in {"warn", "bad"}, ddc
    steps = next_steps(result)
    assert steps[0].startswith("Top concern: Dependency Usage Ratio (DDC)"), steps
    assert any("sweep unused-deps" in step for step in steps), steps


def test_project_without_python_has_no_inflation_or_ddc_value(tmp_path):
    result = _scan(tmp_path, {"src/lib.rs": RUST, "web/App.jsx": JSX})
    assert not result.file_results and result.rust_file_results and result.js_file_results
    rows = _rows(result)
    for label in ("Inflation-to-Code Ratio (ICR)", "Dependency Usage Ratio (DDC)"):
        assert rows[label]["value"].startswith("N/A"), rows[label]
        assert rows[label]["health"] == "n/a", rows[label]
    # The metrics every language has are still measured.
    assert rows["Logic Density Ratio (LDR)"]["health"] != "n/a"
    assert rows["Weighted Deficit Score"]["health"] != "n/a"


def test_project_without_python_is_not_advised_on_python_metrics_or_sweeps(tmp_path):
    result = _scan(tmp_path, {"src/lib.rs": RUST, "web/App.jsx": JSX})
    steps = next_steps(result)
    text = " ".join(steps)
    assert "Dependency Usage" not in text and "Inflation" not in text, steps
    assert "sweep" not in text, steps
    assert "hotspots" not in text, steps
    # It still says where to start: the file with the most severe findings.
    assert any("src/lib.rs" in step for step in steps), steps


def test_the_json_guide_says_the_same(tmp_path):
    """`metric_guide` and `next_steps` of the JSON output come from the same rules."""
    result = _scan(tmp_path, {"src/lib.rs": RUST})
    data = result.to_dict()
    guide = {row["label"]: row for row in data["metric_guide"]}
    assert guide["Dependency Usage Ratio (DDC)"]["value"].startswith("N/A")
    assert "Dependency Usage" not in " ".join(data["next_steps"])


def test_mixed_project_keeps_the_python_advice(tmp_path):
    result = _scan(tmp_path, {"pkg/calc.py": PY_UNUSED_IMPORTS, "src/lib.rs": RUST})
    rows = _rows(result)
    assert rows["Dependency Usage Ratio (DDC)"]["health"] in {"warn", "bad"}
    assert any("sweep unused-deps" in step for step in next_steps(result))


def test_python_file_without_executable_code_has_no_ddc_value(tmp_path):
    """The same average of nothing: DDC is taken over files with executable code."""
    result = _scan(tmp_path, {"pkg/notes.py": '"""Only a docstring."""\n'})
    ddc = _rows(result)["Dependency Usage Ratio (DDC)"]
    assert ddc["value"].startswith("N/A") and ddc["health"] == "n/a", ddc


def _summary_inflation(result) -> str:
    from slop_detector.renderer_markdown import generate_markdown_report

    line = next(
        line
        for line in generate_markdown_report(result).splitlines()
        if line.startswith("| **Inflation (Jargon)**")
    )
    return line.split("|")[2].strip()


def test_markdown_summary_does_not_state_an_inflation_nobody_measured(tmp_path):
    assert _summary_inflation(_scan(tmp_path / "rs", {"src/lib.rs": RUST})).startswith("N/A")
    # Positive control: a Python project states its measured value.
    assert _summary_inflation(_scan(tmp_path / "py", {"pkg/calc.py": PY_UNUSED_IMPORTS})) == "0.00"


def test_a_clean_project_without_python_is_healthy_in_what_was_measured(tmp_path):
    """Two of its metrics read N/A: "All metrics are healthy" would count them."""
    clean_rust = "pub fn add(a: u8, b: u8) -> u8 {\n    a + b\n}\n"
    steps = next_steps(_scan(tmp_path / "rs", {"src/lib.rs": clean_rust}))
    assert steps[0].startswith("All measured metrics are healthy"), steps
    # Positive control: with every metric measured the sentence is unchanged.
    python = next_steps(
        _scan(tmp_path / "py", {"pkg/calc.py": "def add(a, b):\n    return a + b\n"})
    )
    assert python[0].startswith("All metrics are healthy"), python
