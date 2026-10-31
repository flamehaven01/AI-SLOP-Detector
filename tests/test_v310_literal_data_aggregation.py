"""v3.10 P2-B: static literal data modules do not dilute the project score.

Dict-literal data modules could hold almost all of a project's line weight
and move its band. A file with no code to judge scored 0
and counted as that many lines of defect-free code.

Contract:
- `literal_data_module` (file flag) needs: only a module docstring, leading
  `from __future__ import ...` directives and
  assignments of static literals to plain names (constants, containers of
  them, signed numbers); no other import, def, class, control flow, call,
  comprehension, f-string, name reference, operator or unpacking (also of a
  literal: `{**{...}}`); at least one assignment; no pattern finding and no
  pattern error.
- The project weighted score leaves flagged files out of the line weight;
  file results, findings and file counts are unchanged.
- scan_coverage.aggregation_exclusions discloses candidates and the applied
  decision; when every scored file is a candidate nothing is excluded
  (original aggregation, applied false, reason no_scorable_code). No key when
  there is no candidate.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from slop_detector.core import SlopDetector

FLAG = "literal_data_module"

DATA = '''
    """Lookup table."""
    TABLE = {
        "a": 1,
        "b": -2.5,
        "c": (1, 2),
        "d": [None, True, ...],
        "e": {"x", b"y"},
    }
    OTHER = LABEL = "text"
    '''


def _flags(tmp_path: Path, source: str) -> list:
    path = tmp_path / "mod.py"
    path.write_text(textwrap.dedent(source), encoding="utf-8")
    return SlopDetector(read_only=True).analyze_file(str(path)).flags


def test_static_literal_module_is_flagged(tmp_path):
    assert FLAG in _flags(tmp_path, DATA)


@pytest.mark.parametrize(
    "extra",
    [
        "import os",
        "def f():\n    return 1",
        "class C:\n    X = 1",
        "if True:\n    Y = 1",
        "Y = dict(a=1)",
        "Y = [i for i in (1, 2)]",
        "Y = f'{OTHER}'",
        "Y = OTHER",
        "Y = 1 + 2",
        "Y = not True",
        "Y = -'a'",
        "Y = -(1, 2)",
        "Y = {**TABLE}",
        "Y = {**{'x': 1}}",
        "Y = [*TABLE]",
        "from __future__ import annotations",
        "from os import path",
        "from . import sibling",
        "TABLE['f'] = 2",
        "A, B = 1, 2",
        "Y: dict = {}",
        "'not a docstring'",
    ],
)
def test_any_code_disqualifies(tmp_path, extra):
    flags = _flags(tmp_path, textwrap.dedent(DATA) + extra + "\n")
    assert "parse_error" not in flags  # judged as code, not as a broken file
    assert FLAG not in flags


@pytest.mark.parametrize(
    "head",
    [
        "from __future__ import unicode_literals\n",
        '"""Table."""\nfrom __future__ import annotations\n',
        '"""Table."""\nfrom __future__ import annotations\nfrom __future__ import division\n',
    ],
)
def test_future_directive_at_the_top_is_allowed(tmp_path, head):
    # Probability tables: a compiler directive, then one dict.
    assert FLAG in _flags(tmp_path, head + "TABLE = {'a': -3.6, 'b': -10.5}\n")


@pytest.mark.parametrize(
    "head",
    [
        # `from .__future__ import x` is a package-relative import, not the directive.
        "from .__future__ import x\n",
        "from os import path\n",
        "from __future__ import annotations\nfrom os import path\n",
    ],
)
def test_a_leading_import_other_than_future_disqualifies(tmp_path, head):
    assert FLAG not in _flags(tmp_path, head + "TABLE = {'a': 1}\n")


def test_docstring_only_or_empty_is_not_data(tmp_path):
    assert FLAG not in _flags(tmp_path, '"""Only prose."""\n')
    assert FLAG not in _flags(tmp_path, "")


def test_a_finding_disqualifies(tmp_path):
    assert FLAG not in _flags(tmp_path, DATA + "    # TODO: regenerate the table\n")


def test_a_pattern_error_disqualifies(tmp_path, monkeypatch):
    from slop_detector.patterns.placeholder import TodoCommentPattern

    def boom(self, *args, **kwargs):
        raise RuntimeError("pattern failed")

    monkeypatch.setattr(TodoCommentPattern, "check", boom)
    path = tmp_path / "mod.py"
    path.write_text(textwrap.dedent(DATA), encoding="utf-8")
    result = SlopDetector(read_only=True).analyze_file(str(path))
    assert result.pattern_errors
    assert FLAG not in result.flags


CODE = """
    def parse(value):
        try:
            return int(value)
        except:
            pass
    """


def _big_data(n: int) -> str:
    rows = "\n".join(f'    "k{i}": {i},' for i in range(n))
    return f"TABLE = {{\n{rows}\n}}\n"


def _project(tmp_path: Path, files: dict, weighted: bool = True):
    for name, source in files.items():
        (tmp_path / name).write_text(textwrap.dedent(source), encoding="utf-8")
    detector = SlopDetector(read_only=True)
    if not weighted:
        detector.config.use_weighted_analysis = lambda: False  # type: ignore[method-assign]
    return detector.analyze_project(str(tmp_path))


def _by_name(result) -> dict:
    return {Path(r.file_path).name: r for r in result.file_results}


def test_data_weight_leaves_the_project_score(tmp_path):
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    alone = _project(tmp_path / "a", {"code.py": CODE})
    mixed = _project(tmp_path / "b", {"code.py": CODE, "table.py": _big_data(400)})
    files = _by_name(mixed)
    data = files["table.py"]
    assert FLAG in data.flags and FLAG not in files["code.py"].flags
    assert mixed.total_files == 2  # the data file is still analyzed and listed
    assert mixed.weighted_deficit_score == pytest.approx(alone.weighted_deficit_score)
    assert mixed.weighted_deficit_score == pytest.approx(files["code.py"].deficit_score)
    assert mixed.scan_coverage["aggregation_exclusions"] == {
        "reason": FLAG,
        "candidates": 1,
        "candidate_lines": data.ldr.total_lines,
        "applied": True,
        "files": 1,
        "lines": data.ldr.total_lines,
    }
    assert data.ldr.total_lines >= 400


def test_all_data_keeps_the_original_aggregation(tmp_path):
    result = _project(tmp_path, {"t1.py": _big_data(10), "t2.py": DATA})
    files = _by_name(result)
    assert all(FLAG in r.flags for r in files.values())
    lines = sum(r.ldr.total_lines for r in files.values())
    assert result.weighted_deficit_score == pytest.approx(
        sum(r.deficit_score * r.ldr.total_lines for r in files.values()) / lines
    )
    assert result.scan_coverage["aggregation_exclusions"] == {
        "reason": FLAG,
        "candidates": 2,
        "candidate_lines": lines,
        "applied": False,
        "files": 0,
        "lines": 0,
        "not_applied_reason": "no_scorable_code",
    }


def test_unweighted_aggregation_is_not_changed(tmp_path):
    result = _project(tmp_path, {"code.py": CODE, "table.py": _big_data(50)}, weighted=False)
    files = _by_name(result)
    assert result.weighted_deficit_score == pytest.approx(
        sum(r.deficit_score for r in files.values()) / 2
    )
    disclosure = result.scan_coverage["aggregation_exclusions"]
    assert disclosure["applied"] is False and disclosure["files"] == 0
    assert disclosure["not_applied_reason"] == "unweighted_aggregation"


def test_no_candidate_no_key(tmp_path):
    result = _project(tmp_path, {"code.py": CODE})
    assert "aggregation_exclusions" not in result.scan_coverage


def test_flag_and_project_score_survive_the_cache(tmp_path):
    project = tmp_path / "p"
    project.mkdir()
    (project / "code.py").write_text(textwrap.dedent(CODE), encoding="utf-8")
    (project / "table.py").write_text(_big_data(100), encoding="utf-8")
    config = tmp_path / "cfg.yaml"
    db = (tmp_path / "cache.db").as_posix()
    config.write_text(f"advanced:\n  analysis_cache_db: '{db}'\n", encoding="utf-8")
    cold = SlopDetector(config_path=str(config)).analyze_project(str(project))
    warm = SlopDetector(config_path=str(config)).analyze_project(str(project))
    assert Path(db).exists()
    assert FLAG in _by_name(warm)["table.py"].flags
    assert warm.weighted_deficit_score == cold.weighted_deficit_score
    assert (
        warm.scan_coverage["aggregation_exclusions"] == cold.scan_coverage["aggregation_exclusions"]
    )
    assert cold.scan_coverage["aggregation_exclusions"]["applied"] is True
