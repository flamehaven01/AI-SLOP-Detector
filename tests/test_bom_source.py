"""A UTF-8 byte order mark is not a syntax error.

Python accepts a UTF-8 BOM at the start of a source file, and Windows editors
write one. The detector decoded files as plain utf-8, kept U+FEFF, and
ast.parse rejected it: a valid file scored 100 (parse_error), and the same
failure silently emptied package __init__ bindings and dependency
declarations read from BOM files.
"""

from __future__ import annotations

from pathlib import Path

from slop_detector.analysis.connection_resolution import _parse
from slop_detector.analysis.import_graph import _read_init_bindings
from slop_detector.core import SlopDetector
from slop_detector.core_project import is_parse_error
from slop_detector.dependency_declarations import declared_requirements

BOM = b"\xef\xbb\xbf"


def test_bom_file_is_analyzed_not_a_parse_error(tmp_path: Path):
    path = tmp_path / "mod.py"
    path.write_bytes(BOM + b"def f(x):\n    return x + 1\n")
    result = SlopDetector(read_only=True).analyze_file(str(path))
    assert not is_parse_error(result)
    assert result.deficit_score < 100.0


def test_bom_init_keeps_its_bindings(tmp_path: Path):
    init = tmp_path / "pkg" / "__init__.py"
    init.parent.mkdir()
    init.write_bytes(BOM + b"from .core import thing\n")
    bindings = _read_init_bindings(init, {})
    assert "thing" in bindings.member


def test_bom_module_parses_for_connection_resolution(tmp_path: Path):
    path = tmp_path / "m.py"
    path.write_bytes(BOM + b"x = 1\n")
    tree, _ = _parse(path)
    assert tree is not None


def test_bom_requirements_first_line_is_a_clean_name(tmp_path: Path):
    path = tmp_path / "requirements.txt"
    path.write_bytes(BOM + b"numpy>=1.0\nrequests\n")
    assert declared_requirements(path)[0] == "numpy>=1.0"


def test_bom_setup_py_declares_its_requirements(tmp_path: Path):
    path = tmp_path / "setup.py"
    path.write_bytes(BOM + b"from setuptools import setup\nsetup(install_requires=['numpy'])\n")
    assert declared_requirements(path) == ["numpy"]
