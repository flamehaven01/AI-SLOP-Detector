"""S0-P0 (FH-H3-3-WORK-ORDER-REDESIGN): every item is bound to the bytes the
scan analyzed, and every item has its own identity.

SHA256(bytes the AST was built from) == FileAnalysis.source_sha256 == the
record's source_sha256; a file changed after the scan is VOID, never rebound
to the new content; an id distinguishes the rule, the symbol and the subject.
"""

import hashlib
import json

import pytest

import slop_detector.ai_report as ai_report
from slop_detector.ai_report import AiReportInvalid, MISSING, build_records
from slop_detector.ai_report_md import render_ai_report_md
from slop_detector.analysis_cache import FileAnalysisCache, deserialize_file_analysis, serialize_file_analysis
from slop_detector.core import SlopDetector
from slop_detector.report_view import build_report_view

# One function, four unused parameters: four findings at the same line.
FOUR = '''
def generate(path, num_functions=3, add_cross_lang=False, add_mutable_defaults=False, add_bare_except=False):
    return {"path": path}
'''
TWO_TODOS = '''
def work(x):
    # TODO: validate x
    y = x + 1
    # TODO: validate x
    return y
'''


def _write(tmp_path, name, text, raw=None):
    (tmp_path / "pyproject.toml").write_text("", encoding="utf-8")
    path = tmp_path / "pkg" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    if raw is not None:
        path.write_bytes(raw)
    else:
        path.write_text(text, encoding="utf-8")
    return path


def _project(tmp_path):
    return SlopDetector(read_only=True).analyze_project(str(tmp_path))


def _items(result):
    return build_records(build_report_view(result))[1:]


def test_the_scan_binds_the_bytes_it_analyzed(tmp_path):
    raw = b"\xef\xbb\xbf" + FOUR.encode("utf-8")  # a BOM: the decoded text differs from the bytes
    path = _write(tmp_path, "gen.py", None, raw=raw)
    detector = SlopDetector()
    detector._analysis_cache = FileAnalysisCache(tmp_path / "cache.db")
    first = detector.analyze_file(str(path))
    assert first.source_sha256 == hashlib.sha256(raw).hexdigest()
    assert first.to_dict()["source_sha256"] == first.source_sha256
    assert deserialize_file_analysis(serialize_file_analysis(first)).source_sha256 == first.source_sha256
    again = detector.analyze_file(str(path))  # a cache hit keeps the binding
    assert again.source_sha256 == first.source_sha256


def test_a_string_is_bound_to_the_string_it_analyzed():
    result = SlopDetector(read_only=True).analyze_code_string(FOUR, "gen.py")
    assert result.source_sha256 == hashlib.sha256(FOUR.encode("utf-8")).hexdigest()


def test_a_file_changed_after_the_scan_is_void_not_rebound(tmp_path):
    path = _write(tmp_path, "gen.py", FOUR)
    scanned = hashlib.sha256(path.read_bytes()).hexdigest()
    result = _project(tmp_path)
    path.write_text(FOUR + "\n# edited after the scan\n", encoding="utf-8")
    items = _items(result)
    assert items and {r["source_sha256"] for r in items} == {scanned}  # never the new content
    text = render_ai_report_md(result)
    assert "def generate(" not in text  # no code from content the scan did not analyze
    assert text.count("VOID: the file changed after the scan") == len(items)


def test_a_result_without_a_scan_hash_is_missing_never_reread(tmp_path):
    _write(tmp_path, "gen.py", FOUR)
    result = _project(tmp_path)
    for f in result.file_results:
        payload = json.loads(serialize_file_analysis(f))
        payload.pop("source_sha256", None)  # a result written before the field existed
        restored = deserialize_file_analysis(json.dumps(payload))
        assert restored.source_sha256 == ""
        f.source_sha256 = restored.source_sha256
    items = _items(result)
    assert items and {r["source_sha256"] for r in items} == {MISSING}
    text = render_ai_report_md(result)
    assert "def generate(" not in text and text.count("MISSING: no scan-time hash") == len(items)


def test_four_unused_parameters_are_four_items(tmp_path):
    _write(tmp_path, "gen.py", FOUR)
    result = _project(tmp_path)
    [f] = result.file_results
    unused = [i for i in f.pattern_issues if i.pattern_id == "ignored_parameter"]
    assert sorted(i.subject for i in unused) == [
        "add_bare_except", "add_cross_lang", "add_mutable_defaults", "num_functions"]
    assert {i.symbol for i in unused} == {"generate"}
    ids = [r["id"] for r in _items(result) if r["rule"] == "ignored_parameter"]
    assert len(ids) == 4 and len(set(ids)) == 4


def test_ids_survive_a_line_shift_and_change_with_the_evidence(tmp_path):
    path = _write(tmp_path, "work.py", TWO_TODOS)
    before = {r["id"] for r in _items(_project(tmp_path))}
    path.write_text("\n\n\n" + TWO_TODOS, encoding="utf-8")  # every line moves down
    assert {r["id"] for r in _items(_project(tmp_path))} == before
    path.write_text(TWO_TODOS.replace("# TODO: validate x\n    return", "# TODO: check x\n    return"), encoding="utf-8")
    after = {r["id"] for r in _items(_project(tmp_path))}
    assert len(after & before) == len(before) - 1  # only the edited line's item changed


def test_two_identical_lines_in_one_function_stay_two_items(tmp_path):
    # the same text, told apart by the lines around it, not by a number
    _write(tmp_path, "work.py", TWO_TODOS)
    todos = [r for r in _items(_project(tmp_path)) if r["rule"] == "todo_comment"]
    assert len(todos) == 2 and len({r["id"] for r in todos}) == 2


def test_a_symbol_level_id_survives_a_comment_above_the_def(tmp_path):
    path = _write(tmp_path, "gen.py", FOUR)
    before = {r["id"] for r in _items(_project(tmp_path)) if r["rule"] == "ignored_parameter"}
    # the line right above the def changes (FOUR starts with a blank line)
    path.write_text("# a new comment above\n" + FOUR.lstrip("\n"), encoding="utf-8")
    after = {r["id"] for r in _items(_project(tmp_path)) if r["rule"] == "ignored_parameter"}
    assert len(before) == 4 and after == before


def test_one_import_line_naming_two_modules_is_two_items(tmp_path):
    _write(tmp_path, "imp.py", "import nonexistent_pkg_alpha, nonexistent_pkg_beta\n")
    result = _project(tmp_path)
    [f] = result.file_results
    names = sorted(i.subject for i in f.pattern_issues if i.line == 1)
    assert names == ["nonexistent_pkg_alpha", "nonexistent_pkg_beta"]
    ids = [r["id"] for r in _items(result) if r["line"] == 1]
    assert len(ids) == 2 and len(set(ids)) == 2


def test_a_cache_entry_bound_to_other_bytes_is_recomputed(tmp_path, monkeypatch):
    path = _write(tmp_path, "gen.py", FOUR)
    detector = SlopDetector()
    detector._analysis_cache = FileAnalysisCache(tmp_path / "cache.db")
    detector.analyze_file(str(path))
    real_get = detector._analysis_cache.get

    def stale_get(**kwargs):
        hit = real_get(**kwargs)
        if hit is not None:
            hit.source_sha256 = "0" * 64  # an entry that claims other bytes
        return hit

    monkeypatch.setattr(detector._analysis_cache, "get", stale_get)
    again = detector.analyze_file(str(path))
    assert again.source_sha256 == hashlib.sha256(path.read_bytes()).hexdigest()


def test_the_origin_of_the_hashed_content_is_stated(tmp_path):
    path = _write(tmp_path, "gen.py", FOUR)
    from_file = SlopDetector(read_only=True).analyze_file(str(path))
    from_string = SlopDetector(read_only=True).analyze_code_string(FOUR, "gen.py")
    assert (from_file.content_origin, from_string.content_origin) == ("file_bytes", "string_utf8")
    assert {r["source_origin"] for r in _items(_project(tmp_path))} == {"file_bytes"}


def test_identical_lines_are_told_apart_by_their_statement_address(tmp_path):
    # four identical lines (same text, same neighbours): D-S0-1 tells them apart by
    # the locator (body[0]..body[3]); before it, the report was refused
    same = "def f(x):\n" + "    y = x  # TODO: same\n" * 4 + "    return y\n"
    _write(tmp_path, "same.py", same)
    todos = [r for r in _items(_project(tmp_path)) if r["rule"] == "todo_comment"]
    assert len(todos) == 4 and len({r["id"] for r in todos}) == 4
    assert len({r["semantic_key"] for r in todos}) == 1
    assert sorted(r["locator"] for r in todos) == ["body[0]", "body[1]", "body[2]", "body[3]"]


def test_a_duplicate_id_is_never_emitted(tmp_path, monkeypatch):
    _write(tmp_path, "gen.py", FOUR)
    result = _project(tmp_path)
    monkeypatch.setattr(ai_report, "_item_id", lambda item, rel: "Fsame")
    with pytest.raises(AiReportInvalid):
        ai_report.render_ai_report(result)
    with pytest.raises(AiReportInvalid):
        render_ai_report_md(result)


def test_a_symbol_level_id_survives_a_change_to_the_def_line(tmp_path):
    # a symbol-level finding is named by its symbol, not by the text of its def line
    path = _write(tmp_path, "gen.py", FOUR)
    before = {r["id"] for r in _items(_project(tmp_path)) if r["rule"] == "ignored_parameter"}
    path.write_text(FOUR.replace("add_bare_except=False):", "add_bare_except=False, extra_flag=None):"),
                    encoding="utf-8")
    after = {r["id"] for r in _items(_project(tmp_path)) if r["rule"] == "ignored_parameter"}
    assert len(before) == 4 and before <= after and len(after) == 5
