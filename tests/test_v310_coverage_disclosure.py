"""v3.10 coverage disclosure: what a "complete" scan did not look at is counted.

Found by re-scanning NSRW, TOE and RExSyn with 3.9.3: every scan said
`complete: true`, yet
- NSRW has 8 `.lean` files and 1 `.ipynb` notebook (Python code) that appear
  nowhere: `unsupported` only knew a fixed list of other-language extensions;
- RExSyn's own config excludes four named service files, and the exclusion
  count mixed them with 16,714 `.venv` files, so a project hiding its own
  files by config looked the same as one skipping its virtualenv;
- tests are excluded by default and no pattern evaluates them, but the scan
  did not say how many test files went unevaluated.

Contract (additive keys, existing keys unchanged):
- `unsupported` also counts code-bearing files no analyzer reads (notebooks,
  `.lean`, `.mjs`/`.cjs`, ...) and gives `by_extension` counts;
- `excluded.by_source` splits `default` (built-in directory or built-in ignore
  pattern) from `custom` (any other ignore pattern), and `excluded.custom_rules`
  counts files per custom rule;
- `excluded.tests` counts excluded test files;
- the text report states the custom-rule and test counts.
"""

from __future__ import annotations

from pathlib import Path

from slop_detector.core import SlopDetector
from slop_detector.renderer_text import generate_text_report

PY = "def double(x):\n    total = x * 2\n    return total\n"


def _coverage(root: Path, config: Path | None = None) -> dict:
    detector = SlopDetector(config_path=str(config) if config else None, read_only=True)
    result = detector.analyze_project(str(root))
    return result.to_dict()["scan_coverage"], result


def test_notebooks_and_unanalyzed_code_files_are_unsupported(tmp_path):
    (tmp_path / "main.py").write_text(PY, encoding="utf-8")
    (tmp_path / "proof.lean").write_text("theorem t : True := trivial\n", encoding="utf-8")
    (tmp_path / "explore.ipynb").write_text('{"cells": []}\n', encoding="utf-8")
    (tmp_path / "loader.mjs").write_text("export const a = 1;\n", encoding="utf-8")
    (tmp_path / "run.sh").write_text("echo hi\n", encoding="utf-8")
    (tmp_path / "notes.md").write_text("# notes\n", encoding="utf-8")
    (tmp_path / ".venv").mkdir()
    (tmp_path / ".venv" / "vendored.ipynb").write_text('{"cells": []}\n', encoding="utf-8")

    coverage, _ = _coverage(tmp_path)

    unsupported = coverage["unsupported"]
    assert unsupported["total"] == 4
    assert unsupported["by_extension"] == {".ipynb": 1, ".lean": 1, ".mjs": 1, ".sh": 1}
    assert {item["path"] for item in unsupported["files"]} == {
        "proof.lean",
        "explore.ipynb",
        "loader.mjs",
        "run.sh",
    }


def test_custom_rule_exclusions_are_separated_from_default_exclusions(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "kept.py").write_text(PY, encoding="utf-8")
    (tmp_path / "src" / "hidden.py").write_text(PY, encoding="utf-8")
    (tmp_path / ".venv").mkdir()
    (tmp_path / ".venv" / "lib.py").write_text(PY, encoding="utf-8")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_kept.py").write_text(PY, encoding="utf-8")
    config = tmp_path / "cfg.yaml"
    config.write_text('ignore:\n  - "tests/**"\n  - "src/hidden.py"\n', encoding="utf-8")

    coverage, result = _coverage(tmp_path, config)

    excluded = coverage["excluded"]
    assert coverage["analyzed"]["python"] == 1
    assert excluded["total"] == 3
    assert excluded["by_source"] == {"default": 2, "custom": 1}
    assert excluded["custom_rules"] == {"pattern:src/hidden.py": 1}
    assert excluded["tests"] == 1
    report = generate_text_report(result)
    assert "custom rules=1" in report
    assert "tests=1" in report


def test_default_scan_reports_unevaluated_tests(tmp_path):
    (tmp_path / "main.py").write_text(PY, encoding="utf-8")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_a.py").write_text(PY, encoding="utf-8")
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "b_test.py").write_text(PY, encoding="utf-8")
    # A dependency's own tests inside the environment are not project tests.
    site_tests = tmp_path / ".venv" / "lib" / "dep" / "tests"
    site_tests.mkdir(parents=True)
    (site_tests / "test_dep.py").write_text(PY, encoding="utf-8")

    coverage, _ = _coverage(tmp_path)

    excluded = coverage["excluded"]
    assert excluded["tests"] == 2
    assert excluded["by_source"] == {"default": 3, "custom": 0}
    assert excluded["custom_rules"] == {}
