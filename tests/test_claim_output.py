"""H3-3: the claim channel in the scan, the JSON, the cache and every report."""

import ast
import io
import json

from rich.console import Console

import slop_detector.claim_judge as claim_judge
import slop_detector.core as core
from slop_detector.ai_report import render_ai_report
from slop_detector.analysis_cache import FileAnalysisCache, deserialize_file_analysis, serialize_file_analysis
from slop_detector.claim_findings import RULE, ClaimFinding
from slop_detector.core import SlopDetector
from slop_detector.path_facts import facts_for
from slop_detector.renderer_html import render_view_html
from slop_detector.renderer_markdown import generate_markdown_report
from slop_detector.renderer_terminal import claim_line, print_summary
from slop_detector.report_view import REVIEW_CANDIDATE, build_report_view

# A literal result for a live-data promise; no pattern rule reports that body.
# `other` is a constant stub elsewhere: its finding must not absorb the claim.
CANDIDATE = '''
def fetch_exchange_rates(base="USD"):
    """Fetch live exchange rates for the base currency."""
    return {"EUR": 0.92}


def other():
    return 0
'''
# One outcome for a validation promise; return_constant_stub reports the same
# body (one constant return) at the same def line.
MERGED = '''
def validate_token(token):
    """Validate the token signature."""
    return True
'''
# Same function, other evidence: an unused parameter is not "every return is
# a literal", so the candidate stays beside the finding.
OTHER_EVIDENCE = '''
def summarize(records):
    """Compute record counts per signup month."""
    return {"2024-01": 120}
'''
# A constant-return finding at the same def line, but the claim's basis is
# no_concurrent_call: that evidence is not the constant return.
OTHER_BASIS = '''
def upload_all(paths):
    """Upload files in parallel."""
    return []
'''


def _project(tmp_path, files, **kwargs):
    (tmp_path / "pyproject.toml").write_text("", encoding="utf-8")
    for name, text in files.items():
        path = tmp_path / "pkg" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return SlopDetector(read_only=True, **kwargs).analyze_project(str(tmp_path))


def _file(result, name):
    return next(f for f in result.file_results if f.file_path.endswith(name))


def _ai(result):
    return [json.loads(line) for line in render_ai_report(result).splitlines()]


def test_a_contradicted_claim_is_a_review_candidate_with_its_promise(tmp_path):
    result = _project(tmp_path, {"rates.py": CANDIDATE})
    f = _file(result, "rates.py")
    [claim] = f.claim_findings
    assert (claim.function, claim.kind, claim.claim_kind, claim.basis) == (
        "fetch_exchange_rates", RULE, "live_data", "literal_result")
    assert (claim.line, claim.promise_line) == (2, 3)  # the def line; the docstring line
    assert claim.promise == "Fetch live exchange rates for the base currency."
    assert claim.looked_for and claim.why and claim.resolves and claim.same_cause_as == []
    assert f.claim_coverage["state"] == "MEASURED"
    assert (f.claim_coverage["contradicted"], f.claim_coverage["candidates"], f.claim_coverage["merged"]) == (1, 1, 0)
    view = build_report_view(result)
    [item] = [i for i in view.candidates if i.rule == RULE]
    assert item.kind == REVIEW_CANDIDATE and item.line == 2 and item.promise["basis"] == "literal_result"
    assert "promises" in item.message and item.suggestion == claim.resolves
    # the stub elsewhere keeps its own finding, without the promise
    assert all(i.promise is None for i in view.findings)


def test_the_claim_channel_never_changes_the_score(tmp_path, monkeypatch):
    files = {"rates.py": CANDIDATE, "token.py": MERGED, "summary.py": OTHER_EVIDENCE}
    with_claims = _project(tmp_path, files)
    monkeypatch.setattr(core, "claim_analysis", lambda tree, is_test, issues: ([], {"state": "MEASURED"}))
    without = _project(tmp_path, files)
    assert with_claims.weighted_deficit_score == without.weighted_deficit_score
    assert with_claims.overall_status == without.overall_status
    for a, b in zip(with_claims.file_results, without.file_results):
        assert a.deficit_score == b.deficit_score and a.status == b.status
        assert [i.to_dict() for i in a.pattern_issues] == [i.to_dict() for i in b.pattern_issues]


def test_the_same_cause_and_evidence_is_one_item(tmp_path):
    result = _project(tmp_path, {"token.py": MERGED})
    f = _file(result, "token.py")
    [claim] = f.claim_findings
    assert claim.basis == "single_outcome" and claim.same_cause_as == ["return_constant_stub"]
    assert (f.claim_coverage["candidates"], f.claim_coverage["merged"]) == (0, 1)
    view = build_report_view(result)
    assert [i for i in view.candidates if i.rule == RULE] == []
    [finding] = [i for i in view.findings if i.rule == "return_constant_stub"]
    assert "also breaks its docstring" in finding.message and finding.promise["basis"] == "single_outcome"
    [record] = [r for r in _ai(result)[1:] if r["rule"] == "return_constant_stub"]
    assert record["kind"] == "FINDING" and record["promise"]["same_cause_as"] == ["return_constant_stub"]


def test_other_evidence_on_the_same_function_stays_a_candidate(tmp_path):
    result = _project(tmp_path, {"summary.py": OTHER_EVIDENCE, "upload.py": OTHER_BASIS})
    summary, upload = _file(result, "summary.py"), _file(result, "upload.py")
    assert "ignored_parameter" in {i.pattern_id for i in summary.pattern_issues}
    assert [(c.basis, c.same_cause_as) for c in summary.claim_findings] == [("literal_result", [])]
    # the constant-return rule fired on this def line, but the basis differs
    assert "return_constant_stub" in {i.pattern_id for i in upload.pattern_issues}
    assert [(c.basis, c.same_cause_as) for c in upload.claim_findings] == [("no_concurrent_call", [])]
    assert {i.message.split(":")[0] for i in build_report_view(result).candidates if i.rule == RULE} == {
        "summarize", "upload_all"}


def test_the_json_and_the_cache_keep_every_field(tmp_path):
    f = _file(_project(tmp_path, {"rates.py": CANDIDATE, "token.py": MERGED}), "token.py")
    data = f.to_dict()
    assert data["claim_findings"] == [c.to_dict() for c in f.claim_findings]
    assert data["claim_coverage"] == f.claim_coverage and data["claim_coverage"] is not f.claim_coverage
    restored = deserialize_file_analysis(serialize_file_analysis(f))
    assert [c.to_dict() for c in restored.claim_findings] == data["claim_findings"]
    assert all(isinstance(c, ClaimFinding) for c in restored.claim_findings)
    assert restored.claim_coverage == f.claim_coverage


def test_a_failed_channel_is_unmeasured_never_cached_and_never_zero(tmp_path, monkeypatch):
    path = tmp_path / "pkg" / "rates.py"
    (tmp_path / "pyproject.toml").write_text("", encoding="utf-8")
    path.parent.mkdir()
    path.write_text(CANDIDATE, encoding="utf-8")
    detector = SlopDetector()
    detector._analysis_cache = FileAnalysisCache(tmp_path / "cache.db")
    puts = []
    monkeypatch.setattr(detector._analysis_cache, "put", lambda **kw: puts.append(kw))

    def boom(tree, is_test, issues):
        raise RecursionError("deep")

    monkeypatch.setattr(core, "claim_analysis", boom)
    failed = detector.analyze_file(str(path))
    assert failed.claim_findings == [] and failed.claim_coverage == {"state": "UNMEASURED", "error_type": "RecursionError"}
    assert puts == []
    monkeypatch.undo()
    # one judgment failing is counted, and the result is not cached either
    monkeypatch.setattr(detector._analysis_cache, "put", lambda **kw: puts.append(kw))
    monkeypatch.setitem(claim_judge.RULES, "live_data", lambda *a: 1 / 0)
    partial = detector.analyze_file(str(path))
    assert partial.claim_coverage["state"] == "MEASURED" and partial.claim_coverage["unmeasured"] == 1
    assert partial.claim_findings == [] and puts == []
    monkeypatch.undo()
    monkeypatch.setattr(detector._analysis_cache, "put", lambda **kw: puts.append(kw))
    detector.analyze_file(str(path))
    assert len(puts) == 1  # a fully measured result is cached


def test_every_report_states_the_channel_and_never_writes_zero_when_not_measured(tmp_path):
    result = _project(tmp_path, {"rates.py": CANDIDATE})
    view = build_report_view(result)
    assert claim_line(view).startswith("1 docstring promise(s): 1 contradicted (1 candidate(s), 0 merged")
    out = io.StringIO()
    print_summary(view, console=Console(file=out, width=240, color_system=None))
    assert "Promises" in out.getvalue() and "1 docstring promise(s)" in out.getvalue()
    assert "Docstring promises: 1 docstring promise(s)" in generate_markdown_report(result)
    assert "Docstring promises: 1 docstring promise(s)" in render_view_html(view)
    for state, words in (("UNMEASURED", "not measured"), ("SKIPPED", "skipped")):
        for f in result.file_results:
            f.claim_coverage, f.claim_findings = {"state": state}, []
        failed = build_report_view(result)
        assert claim_line(failed).startswith(words)
        assert "0 docstring promise" not in generate_markdown_report(result)
        header = _ai(result)[0]
        assert header["measurement"]["claims"] == state and header["claims"]["contradicted"] == 0


def test_the_ai_report_carries_the_promise_and_the_claim_counts(tmp_path):
    result = _project(tmp_path, {"rates.py": CANDIDATE, "token.py": MERGED})
    header, items = _ai(result)[0], _ai(result)[1:]
    assert header["measurement"]["claims"] == "MEASURED"
    claims = header["claims"]
    assert (claims["contradicted"], claims["candidates"], claims["merged"]) == (2, 1, 1)
    assert claims["extracted_claims"] == 2 and isinstance(claims["undecided_by_reason"], dict)
    [record] = [r for r in items if r["rule"] == RULE]
    assert record["kind"] == "REVIEW_CANDIDATE" and record["channel_state"] == "MEASURED"
    assert record["promise"]["promise"] == "Fetch live exchange rates for the base currency."
    assert record["fix"] == record["promise"]["resolves"]
    # an item without a promise keeps its record shape
    assert all("promise" not in r for r in items if r["rule"] not in (RULE, "return_constant_stub"))


def test_skipped_test_code_and_no_python_are_counted_not_judged(tmp_path):
    tree = ast.parse(CANDIDATE)
    facts = facts_for(tmp_path / "pkg" / "rates.py", tmp_path)
    assert core._claim_channel(tree, {"patterns"}, facts, []) == ([], {"state": "SKIPPED"})
    (tmp_path / "pyproject.toml").write_text("", encoding="utf-8")
    path = tmp_path / "tests" / "test_rates.py"
    path.parent.mkdir()
    path.write_text(CANDIDATE, encoding="utf-8")  # a project scan leaves tests/ out; one file is judged
    f = SlopDetector(read_only=True).analyze_file(str(path))
    assert f.claim_findings == [] and f.claim_coverage["not_analyzed_by_reason"]["test_code"] == 1
    assert build_report_view(SlopDetector(read_only=True).analyze_project(str(tmp_path / "none"))).claims.state == (
        "NOT_APPLICABLE")
