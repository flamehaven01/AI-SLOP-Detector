"""Scoring and classification consistency: one result, one meaning, every surface.

Contract (docs: reconstruction section 7):
- one band set for every score on the 0-100 deficit scale (Python file,
  project, Go, JS): CLEAN <30, SUSPICIOUS 30-<50, INFLATED_SIGNAL 50-<70,
  CRITICAL_DEFICIT >=70, decided by one function;
- a flag (dependency_noise) never replaces the band;
- the result reports the file role and which metrics were skipped for it, and
  no role skips inflation (a dataclass cannot lower a score);
- consumers render the canonical result: the CI adapter applies its thresholds
  only to metrics that apply to the file, and cross-file analysis has no score;
- a file that fails to parse keeps a weight in the project score.
"""

from __future__ import annotations

import importlib
import importlib.util
import textwrap
from pathlib import Path

import pytest

from slop_detector.core import SlopDetector
from slop_detector.models import SlopStatus

JARGON = """
# Robust, scalable, production-ready, enterprise-grade, cutting-edge, sophisticated,
# state-of-the-art, holistic, comprehensive, mission-critical, fault-tolerant engine.
# Robust, scalable, production-ready, enterprise-grade, cutting-edge, sophisticated.
def f(x):
    return x
"""


@pytest.fixture
def root(tmp_path_factory):
    return tmp_path_factory.mktemp("proj")


def _write(path: Path, source: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(source).lstrip("\n"), encoding="utf-8")
    return path


def _bands():
    """slop_detector.diagnostic_bands, or an assertion failure before it exists."""
    assert importlib.util.find_spec("slop_detector.diagnostic_bands"), "diagnostic_bands missing"
    return importlib.import_module("slop_detector.diagnostic_bands")


def _analyze(path: Path):
    return SlopDetector(read_only=True).analyze_file(str(path))


# ---------------------------------------------------------------------------
# V8: one band set, one function
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "score,status",
    [
        (0.0, SlopStatus.CLEAN),
        (29.99, SlopStatus.CLEAN),
        (30.0, SlopStatus.SUSPICIOUS),
        (49.99, SlopStatus.SUSPICIOUS),
        (50.0, SlopStatus.INFLATED_SIGNAL),
        (69.99, SlopStatus.INFLATED_SIGNAL),
        (70.0, SlopStatus.CRITICAL_DEFICIT),
        (100.0, SlopStatus.CRITICAL_DEFICIT),
    ],
)
def test_one_band_function(score, status):
    assert _bands().classify_deficit(score) is status


def test_project_status_uses_the_file_bands(root):
    """A weighted project score of 50-70 is INFLATED_SIGNAL, as for a file (was CRITICAL)."""
    from slop_detector.core_project import build_project_analysis

    result = _analyze(_write(root / "m.py", "def f(x):\n    return x\n"))
    result.deficit_score = 55.0
    project = build_project_analysis(
        str(root),
        str(root),
        [result],
        [],
        [],
        {"analyzed": {}},
        True,
        lambda dcfs: (0.0, "none"),
        lambda path, results: ([], False, False),
        {},
    )
    assert project.overall_status is SlopStatus.INFLATED_SIGNAL


def test_cli_fallback_project_uses_the_same_aggregation(root, monkeypatch):
    from slop_detector import cli_analysis

    path = _write(root / "m.py", "def f(x):\n    return x\n")
    det = SlopDetector(read_only=True)
    stub = det.analyze_file(str(path))
    stub.deficit_score = 55.0
    monkeypatch.setattr(det, "analyze_file", lambda file_path, root=None: stub)
    project = cli_analysis._build_fallback_project_analysis(det, root)
    assert project.overall_status is SlopStatus.INFLATED_SIGNAL


def test_javascript_uses_the_canonical_bands(root):
    """JS used <20 clean / >=50 critical. A 25.0 score is CLEAN on the shared scale."""
    from slop_detector.languages.js_analyzer import JSAnalyzer

    path = _write(root / "x.js", "// a\n// b\n// c\n// d\nconst x = 1;\n")
    result = JSAnalyzer().analyze(str(path))
    assert result.slop_score == pytest.approx(25.0)
    assert result.status == _bands().classify_deficit(result.slop_score).value


def test_go_uses_the_canonical_bands(root):
    """Go had no INFLATED_SIGNAL band. A 60.3 score is INFLATED_SIGNAL on the shared scale."""
    from slop_detector.languages.go_analyzer import GoAnalyzer

    notes = "".join(f"// note {i}\n" for i in range(120))
    path = _write(root / "x.go", "package main\n\n" + notes + "func f() {}\n")
    result = GoAnalyzer().analyze(str(path))
    assert 50.0 <= result.slop_score < 70.0, result.slop_score
    assert result.status == _bands().classify_deficit(result.slop_score).value


def test_gate_deficit_thresholds_default_to_the_canonical_bands():
    from slop_detector.gate.models import GateThresholds

    bands = _bands()
    assert GateThresholds().deficit_fail == bands.CRITICAL_AT
    assert GateThresholds().deficit_warn == bands.SUSPICIOUS_AT


# ---------------------------------------------------------------------------
# V7: a flag never replaces the band
# ---------------------------------------------------------------------------


def test_dependency_noise_is_a_flag_not_a_status(root):
    mods = ["os", "sys", "json", "re", "csv", "math", "time", "glob", "shutil", "string"]
    source = "".join(f"import {m}\n" for m in mods) + "def f():\n    pass\n\n\ndef g():\n    pass\n"
    result = _analyze(_write(root / "c.py", source))
    assert result.deficit_score >= 70.0
    assert result.status is SlopStatus.CRITICAL_DEFICIT
    assert "dependency_noise" in getattr(result, "flags", []), "flags missing"
    assert "dependency_noise" in result.to_dict().get("flags", [])


# ---------------------------------------------------------------------------
# V1: applicability is reported, and no role skips inflation
# ---------------------------------------------------------------------------


def test_a_dataclass_does_not_lower_the_score(root):
    plain = _analyze(_write(root / "a.py", JARGON))
    model = _analyze(
        _write(
            root / "b.py",
            "from dataclasses import dataclass\n\n\n@dataclass\nclass P:\n    x: int = 0\n"
            + JARGON,
        )
    )
    assert model.deficit_breakdown["inflation_penalty"] > 0
    assert model.deficit_score >= plain.deficit_score


def test_role_and_skipped_metrics_are_reported(root):
    init = _analyze(_write(root / "pkg" / "__init__.py", "import os\nimport sys\n"))
    payload = init.to_dict()
    assert payload.get("file_role") == "init", payload.get("file_role")
    assert sorted(payload.get("skipped_metrics", [None])) == ["ddc", "ldr"]
    source = _analyze(_write(root / "m.py", "def f(x):\n    return x\n")).to_dict()
    assert source.get("file_role") == "source"
    assert source.get("skipped_metrics") == []


# ---------------------------------------------------------------------------
# V2: the CI adapter does not re-judge a metric the score skipped
# ---------------------------------------------------------------------------


def test_gate_does_not_fail_a_metric_the_score_skipped(root):
    from slop_detector.ci_gate import CIGate
    from slop_detector.gate.models import GateMode, GateVerdict

    init = _analyze(_write(root / "pkg" / "__init__.py", "import os\nimport sys\n"))
    assert init.ddc.usage_ratio < 0.5
    assert init.status is SlopStatus.CLEAN
    assert CIGate(mode=GateMode.HARD).evaluate(init).verdict is not GateVerdict.FAIL


def test_gate_still_applies_its_thresholds_to_applicable_metrics(root):
    """Preservation: an ordinary file with unused imports still fails ddc_fail."""
    from slop_detector.ci_gate import CIGate
    from slop_detector.gate.models import GateMode, GateVerdict

    source = "import os\nimport sys\n\n\ndef f(x):\n    return x\n"
    result = _analyze(_write(root / "m.py", source))
    assert result.ddc.usage_ratio < 0.5
    assert CIGate(mode=GateMode.HARD).evaluate(result).verdict is GateVerdict.FAIL


# ---------------------------------------------------------------------------
# V4: a file that fails to parse does not vanish from the project score
# ---------------------------------------------------------------------------


def test_parse_error_keeps_a_weight_and_stays_out_of_metric_averages(root):
    _write(root / "ok.py", "def f(x):\n    return x + 1\n")
    _write(root / "bad.py", "def f(:\n    return 1\n")
    project = SlopDetector(read_only=True).analyze_project(str(root))
    ok = [r for r in project.file_results if r.file_path.endswith("ok.py")][0]
    assert project.weighted_deficit_score > ok.deficit_score
    assert project.overall_status is not SlopStatus.CLEAN
    assert project.avg_inflation < 10.0, project.avg_inflation
    assert getattr(project, "parse_error_files", None) == 1


# ---------------------------------------------------------------------------
# V13: cross-file analysis is evidence, not a second score
# ---------------------------------------------------------------------------


def test_cross_file_report_has_no_score():
    from slop_detector.analysis.cross_file import CrossFileReport

    report = CrossFileReport(project_path=".", total_files=0)
    assert not hasattr(report, "risk_score")
    assert "risk_score" not in report.to_dict()


def test_cache_round_trip_keeps_role_skips_and_flags(root):
    from slop_detector.analysis_cache import deserialize_file_analysis, serialize_file_analysis

    mods = ["os", "sys", "json", "re", "csv", "math", "time", "glob", "shutil", "string"]
    source = "".join(f"import {m}\n" for m in mods) + "def f():\n    pass\n"
    for result in (
        _analyze(_write(root / "c.py", source)),
        _analyze(_write(root / "pkg" / "__init__.py", "import os\n")),
        _analyze(_write(root / "bad.py", "def f(:\n")),
    ):
        restored = deserialize_file_analysis(serialize_file_analysis(result))
        assert (restored.file_role, restored.skipped_metrics, restored.flags) == (
            result.file_role,
            result.skipped_metrics,
            result.flags,
        )
        assert result.flags or result.skipped_metrics


def test_cached_results_from_before_the_contract_are_not_reused():
    from slop_detector.analysis_cache import CACHE_ENGINE_VERSION

    assert CACHE_ENGINE_VERSION not in {f"analysis-cache-v{n}" for n in range(11, 17)}
