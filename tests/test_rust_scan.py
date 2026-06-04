"""Tests for the optional Rust file-discovery hot path."""

from pathlib import Path

from slop_detector.core import SlopDetector
from slop_detector.rust_scan import discover_project_files


def test_discover_project_files_uses_rust_scan_contract(tmp_path, monkeypatch):
    project = tmp_path / "proj"
    (project / "src").mkdir(parents=True)
    file_path = project / "src" / "app.py"
    file_path.write_text("def ok():\n    return 1\n", encoding="utf-8")

    monkeypatch.setattr(
        "slop_detector.rust_scan._run_rust_scan",
        lambda root, include_patterns, ignore_patterns: [str(file_path)],
    )

    files = discover_project_files(project, ["**/*.py"], ["tests/**"])

    assert files == [file_path]


def test_analyze_project_uses_rust_file_discovery(tmp_path, monkeypatch):
    project = tmp_path / "proj"
    project.mkdir()
    file_path = project / "app.py"
    file_path.write_text("def ok():\n    return 1\n", encoding="utf-8")

    monkeypatch.setattr(
        "slop_detector.core.discover_project_files",
        lambda root, include_patterns, ignore_patterns: [file_path],
    )

    detector = SlopDetector()
    result = detector.analyze_project(str(project))

    assert result.total_files == 1
    assert [Path(fr.file_path).name for fr in result.file_results] == ["app.py"]
