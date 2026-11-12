"""FH-WO-002: JS/TS and Go findings reach every report, bound to the bytes
their analyzer read. Scores and the analyzers' findings do not change.
"""

import hashlib
import json
from pathlib import Path

from slop_detector.ai_report import build_records, render_ai_report
from slop_detector.ai_report_md import render_ai_report_md
from slop_detector.core import SlopDetector
from slop_detector.languages.go_analyzer import GoAnalyzer
from slop_detector.languages.js_analyzer import _TS_AVAILABLE, JSAnalyzer
from slop_detector.report_view import FINDING, build_report_view

JS = "function f(a){ console.log(a); var x = 1; if (a == 2) {} }\n"
GO = 'package main\nimport "fmt"\nfunc main() {\n\tfmt.Println("x")\n\t// TODO: later\n\tpanic("no")\n}\n'


def _project(tmp_path, files):
    (tmp_path / "pyproject.toml").write_text("", encoding="utf-8")
    for name, raw in files.items():
        (tmp_path / name).write_bytes(raw)
    return SlopDetector(read_only=True).analyze_project(str(tmp_path))


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def test_js_and_go_findings_reach_the_view_and_the_ai_report(tmp_path):
    result = _project(tmp_path, {"a.js": JS.encode(), "m.go": GO.encode()})
    expected = sum(len(f.issues) for f in result.js_file_results + result.go_file_results)
    assert expected >= 6
    view = build_report_view(result)
    lang = [i for i in view.findings if i.file.endswith((".js", ".go"))]
    assert len(lang) == expected and all(i.kind == FINDING for i in lang)
    assert {i.severity for i in lang} <= {"critical", "high", "medium", "low"}
    records = [json.loads(line) for line in render_ai_report(result).splitlines()]
    items = [r for r in records[1:] if r["file"].endswith((".js", ".go"))]
    assert len(items) == expected and records[0]["findings"] == len(view.findings)
    assert len({r["id"] for r in items}) == expected  # same line, other column or rule: other item
    text = render_ai_report_md(result)
    assert text.count("(the file is the content the scan analyzed)") == len(records) - 1


def test_each_language_result_is_bound_to_the_bytes_its_analyzer_read(tmp_path):
    result = _project(tmp_path, {"a.js": JS.encode(), "m.go": GO.encode()})
    for f in result.js_file_results + result.go_file_results:
        assert f.source_sha256 == _sha(f.file_path) and f.content_origin == "file_bytes"
        assert f.to_dict()["source_sha256"] == f.source_sha256
    items = build_records(build_report_view(result))[1:]
    assert all(r["source_sha256"] == _sha(tmp_path / r["file"]) for r in items)
    assert {r["source_origin"] for r in items} == {"file_bytes"}
    (tmp_path / "a.js").write_bytes(JS.encode() + b"// edited after the scan\n")
    void = render_ai_report_md(result)
    assert "console.log(a)" not in void.split("## WORK-ORDER")[1].split("m.go")[0]
    assert void.count("(VOID: the file changed after the scan") == len(
        [r for r in items if r["file"] == "a.js"]
    )


def test_reading_bytes_leaves_the_analysis_unchanged(tmp_path):
    # CRLF line ends and an undecodable byte: the old read_text path is the reference
    raw_js = JS.replace("\n", "\r\n").encode() + b"\xff// tail\r\n"
    raw_go = GO.replace("\n", "\r\n").encode() + b"\xfe\r\n"
    js_path, go_path = tmp_path / "a.js", tmp_path / "m.go"
    js_path.write_bytes(raw_js)
    go_path.write_bytes(raw_go)
    js, go = JSAnalyzer(), GoAnalyzer()
    js_text = js_path.read_text(encoding="utf-8", errors="ignore")
    go_text = go_path.read_text(encoding="utf-8", errors="ignore")
    if _TS_AVAILABLE:
        js_ref = js._analyze_ast(str(js_path), js_text, "javascript", False, False)
    else:
        js_ref = js._analyze_regex(str(js_path), js_text, "javascript", False)
    go_ref = (
        go._analyze_ast(str(go_path), go_text)
        if hasattr(go, "_analyze_ast") and _go_ts()
        else (go._analyze_regex(str(go_path), go_text))
    )
    for new, ref in ((js.analyze(str(js_path)), js_ref), (go.analyze(str(go_path)), go_ref)):
        a, b = new.to_dict(), ref.to_dict()
        assert a["slop_score"] == b["slop_score"] and a["status"] == b["status"]
        assert [(i["pattern_id"], i["line"], i["message"]) for i in a["issues"]] == [
            (i["pattern_id"], i["line"], i["message"]) for i in b["issues"]
        ]
        assert {k: v for k, v in a.items() if k not in _BINDING} == {
            k: v for k, v in b.items() if k not in _BINDING
        }


_BINDING = {"source_sha256", "content_origin", "issues"}


def test_both_analysis_paths_bind_the_bytes_read(tmp_path, monkeypatch):
    # the regex fallback and the tree-sitter path (when installed) each bind
    # the result, whatever the environment has installed
    from slop_detector.languages import go_analyzer, js_analyzer

    (tmp_path / "a.js").write_bytes(JS.encode())
    (tmp_path / "m.go").write_bytes(GO.encode())
    paths = [False] + [True] * (js_analyzer._TS_AVAILABLE or go_analyzer._TS_AVAILABLE)
    for ts in paths:
        for module, analyzer, name in (
            (js_analyzer, JSAnalyzer(), "a.js"),
            (go_analyzer, GoAnalyzer(), "m.go"),
        ):
            if ts and not module._TS_AVAILABLE:
                continue
            monkeypatch.setattr(module, "_TS_AVAILABLE", ts)
            result = analyzer.analyze(str(tmp_path / name))
            assert result.source_sha256 == _sha(tmp_path / name), (name, ts)
            assert result.issues and all(i.locator for i in result.issues), (name, ts)


def _go_ts():
    from slop_detector.languages import go_analyzer

    return go_analyzer._TS_AVAILABLE


def test_the_project_score_is_the_same_with_or_without_the_language_items(tmp_path):
    result = _project(
        tmp_path, {"a.js": JS.encode(), "m.go": GO.encode(), "p.py": b"def f(x):\n    return x\n"}
    )
    before = (result.weighted_deficit_score, str(result.overall_status))
    view = build_report_view(result)
    assert view.score == result.weighted_deficit_score and before == (
        result.weighted_deficit_score,
        str(result.overall_status),
    )


def test_the_bytes_decode_to_what_read_text_gave(tmp_path):
    from slop_detector.finding_identity import read_source

    path = tmp_path / "a.js"
    path.write_bytes(b"var a = 1;\r\nvar b = 2;\rvar c = 3;\n\xff// tail\r\n")
    text, digest = read_source(str(path))
    assert text == path.read_text(encoding="utf-8", errors="ignore")
    assert digest == _sha(path)
