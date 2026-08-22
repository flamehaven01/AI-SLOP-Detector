"""Regression tests for ``core`` facade delegation seams."""

import ast

from slop_detector.core import SlopDetector


def test_core_facade_delegates_pattern_penalty_to_scoring_helper(monkeypatch):
    detector = SlopDetector()
    calls = []

    def fake_penalty(issues):
        calls.append(issues)
        return 17.0

    monkeypatch.setattr("slop_detector.core.calculate_pattern_penalty", fake_penalty)

    assert detector._calculate_pattern_penalty([]) == 17.0
    assert calls == [[]]


def test_core_facade_delegates_dcf_to_topology_helper(monkeypatch):
    calls = []

    def fake_dcf(tree):
        calls.append(tree)
        return {"Module": 1.0}

    monkeypatch.setattr("slop_detector.core.compute_dcf", fake_dcf)
    tree = ast.parse("value = 1\n")

    assert SlopDetector._compute_dcf(tree) == {"Module": 1.0}
    assert calls == [tree]


def test_analyze_project_delegates_aggregation_to_project_helper(monkeypatch, tmp_path):
    source = tmp_path / "module.py"
    source.write_text("value = 1\n", encoding="utf-8")
    sentinel = object()
    captured = {}

    def fake_build(*args):
        captured["args"] = args
        return sentinel

    monkeypatch.setattr("slop_detector.core.build_project_analysis", fake_build)

    assert SlopDetector().analyze_project(str(tmp_path)) is sentinel
    assert captured["args"][0] == str(tmp_path)
    assert captured["args"][1] == str(tmp_path)
    assert len(captured["args"][2]) == 1
