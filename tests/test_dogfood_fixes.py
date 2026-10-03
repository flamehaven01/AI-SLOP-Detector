"""Fixes for what dogfooding the detector on its own repository found (9e4d4ff).

DF-2 The band module owns the status vocabulary, so `diagnostic_bands`,
     `models`, and `renderer_glossary` no longer form an import cycle.
DF-1 Metadata strings are not claims: a dict key in a vocabulary table, and
     argparse `help=` / `description=` / `epilog=` text. Comments, docstrings,
     messages, and ordinary string values still are.
DF-6 `sweep dead-code` calls a file placeholder-only only when it has no
     substantive implementation and every function is an empty stub. A TODO
     string, one `except: pass`, a Protocol or abstract method, or a call-only
     function does not make a file placeholder-only.
DF-4 The Markdown executive summary pairs the status with the score it was
     derived from (the weighted deficit for a project).
"""

from __future__ import annotations

import textwrap
from pathlib import Path
from typing import List

import pytest

from slop_detector.core import SlopDetector

SRC = Path(__file__).resolve().parents[1] / "src"
PKG = SRC / "slop_detector"


@pytest.fixture
def root(tmp_path_factory):
    return tmp_path_factory.mktemp("proj")


def _write(path: Path, source: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(source).lstrip("\n"), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# DF-2: no import cycle through the band module
# ---------------------------------------------------------------------------


def test_the_band_module_owns_the_status_enum():
    from slop_detector import diagnostic_bands, models

    assert diagnostic_bands.SlopStatus.__module__ == "slop_detector.diagnostic_bands"
    assert models.SlopStatus is diagnostic_bands.SlopStatus


def test_bands_models_and_glossary_form_no_import_cycle():
    from slop_detector.analysis.import_graph import build_import_edges, hard_graph

    files = [PKG / "diagnostic_bands.py", PKG / "models.py", PKG / "renderer_glossary.py"]
    graph = hard_graph(build_import_edges(SRC, files))
    names = {str(p.resolve()): p.name for p in files}

    def reaches(start, goal, seen):
        for nxt in graph.get(start, ()):
            if nxt == goal or (
                nxt in names and nxt not in seen and reaches(nxt, goal, seen | {nxt})
            ):
                return True
        return False

    cyclic = [names[f] for f in names if reaches(f, f, {f})]
    assert cyclic == [], cyclic


# ---------------------------------------------------------------------------
# DF-1: metadata strings are not claims
# ---------------------------------------------------------------------------


def _words(root: Path, source: str) -> List[str]:
    path = _write(root / "m.py", source)
    return [
        d["word"]
        for d in SlopDetector(read_only=True).analyze_file(str(path)).inflation.jargon_details
    ]


def test_a_dict_key_in_a_vocabulary_table_is_not_a_claim(root):
    source = 'REQUIREMENTS = {\n    "production-ready": ["tests"],\n    "scalable": ["cache"],\n}\n'
    assert _words(root, source) == []


def test_argparse_help_and_description_are_not_claims(root):
    source = (
        "import argparse\n\n"
        'parser = argparse.ArgumentParser(description="A scalable tool", epilog="Robust output.")\n'
        "parser.add_argument(\n"
        '    "--strict",\n'
        '    help="Fail if production-ready or fault-tolerant claims lack "\n'
        '    "integration tests",\n'
        ")\n"
    )
    assert _words(root, source) == []


@pytest.mark.parametrize(
    "source,word",
    [
        ("# A production-ready service.\nX = 1\n", "production-ready"),
        (
            'def f():\n    """Run.\n\n    Production-ready path.\n    """\n    return 1\n',
            "production-ready",
        ),
        ('import logging\nlogging.info("production-ready service")\n', "production-ready"),
        ('message = "a scalable service"\n', "scalable"),
        ('CONFIG = {"summary": "a scalable service"}\n', "scalable"),
        ('import argparse\nargparse.ArgumentParser().error("not scalable")\n', "scalable"),
    ],
    ids=[
        "comment",
        "docstring",
        "log-message",
        "assigned-string",
        "dict-value",
        "non-metadata-call",
    ],
)
def test_genuine_prose_claims_are_still_claims(root, source, word):
    assert word in _words(root, source)


@pytest.mark.parametrize("rel", ["metrics/context_jargon.py", "cli_parsers.py"])
def test_the_detector_source_passes_its_own_strict_claims_gate(rel):
    from slop_detector.ci_gate import CIGate

    analysis = SlopDetector(read_only=True).analyze_file(str(PKG / rel), root=str(SRC))
    assert (
        CIGate(claims_strict=True)._has_uncovered_production_claims(analysis.context_jargon)
        is False
    )


# ---------------------------------------------------------------------------
# DF-6: placeholder-only means no implementation at all
# ---------------------------------------------------------------------------


def _placeholder_only(root: Path, source: str) -> bool:
    from slop_detector.operations_cleanup import _looks_like_dead_code

    return _looks_like_dead_code(str(_write(root / "m.py", source)))


IMPLEMENTED = "def add(a, b):\n    return a + b\n"


@pytest.mark.parametrize(
    "extra",
    [
        'MARKER = "TODO: not a placeholder"\n',
        "# TODO: refine the rounding\n",
        "def safe(x):\n    try:\n        return int(x)\n    except ValueError:\n        pass\n",
        "from typing import Protocol\n\n\nclass Store(Protocol):\n    def get(self, key): ...\n",
        "from abc import ABC, abstractmethod\n\n\nclass Base(ABC):\n    @abstractmethod\n    def run(self):\n        raise NotImplementedError\n",
    ],
    ids=["todo-string", "todo-comment", "except-pass", "protocol-method", "abstract-method"],
)
def test_an_implemented_file_is_not_placeholder_only(root, extra):
    assert _placeholder_only(root, IMPLEMENTED + "\n\n" + extra) is False


def test_a_call_only_function_is_not_a_placeholder(root):
    assert _placeholder_only(root, "def configure(c):\n    c.add(1)\n    c.add(2)\n") is False


def test_a_pure_interface_file_is_not_placeholder_only(root):
    source = "from typing import Protocol\n\n\nclass Store(Protocol):\n    def get(self, key): ...\n\n    def put(self, key, value): ...\n"
    assert _placeholder_only(root, source) is False


def test_an_all_stub_file_is_placeholder_only(root):
    source = 'def load():\n    """Load."""\n    pass\n\n\ndef save():\n    ...\n\n\ndef close():\n    return None\n'
    assert _placeholder_only(root, source) is True


@pytest.mark.parametrize(
    "rel",
    [
        "auth/sso.py",
        "autofix/engine.py",
        "languages/base.py",
        "languages/go_analyzer.py",
        "metrics/ldr.py",
        "operations_cleanup.py",
        "operations_manifest.py",
        "path_facts.py",
        "patterns/base.py",
        "patterns/placeholder.py",
        "question_generator.py",
    ],
)
def test_the_eleven_self_false_positives_are_not_placeholder_only(rel):
    from slop_detector.operations_cleanup import _looks_like_dead_code

    assert _looks_like_dead_code(str(PKG / rel)) is False


def test_the_intentional_placeholder_corpus_is_still_reported():
    from slop_detector.operations_cleanup import _collect_dead_code_issues

    corpus = Path(__file__).resolve().parent / "corpus"
    det = SlopDetector(read_only=True)
    results = [det.analyze_file(str(p)) for p in sorted(corpus.glob("*.py"))]

    class _Result:
        file_results = results
        priority_hotspots: list = []

    reported = {Path(issue["file_path"]).name for issue in _collect_dead_code_issues(_Result())}
    assert {"placeholder_code.py", "test_case_1_ai_slop.py"} <= reported, reported


# ---------------------------------------------------------------------------
# DF-4: Markdown summary pairs the status with the score it came from
# ---------------------------------------------------------------------------


def test_markdown_summary_shows_the_score_behind_the_status(root):
    from slop_detector.renderer_markdown import generate_markdown_report

    _write(root / "a.py", "def f(x):\n    return x + 1\n")
    project = SlopDetector(read_only=True).analyze_project(str(root))
    project.avg_deficit_score = 28.0
    project.weighted_deficit_score = 32.0
    project.overall_status = __import__(
        "slop_detector.models", fromlist=["SlopStatus"]
    ).SlopStatus.SUSPICIOUS
    summary = (
        generate_markdown_report(project).split("## 1. Executive Summary", 1)[1].split("\n\n", 1)[0]
    )
    row = [line for line in summary.splitlines() if "SUSPICIOUS" in line]
    assert row, summary
    assert "32.00" in row[0] and "Weighted" in row[0], row[0]
    assert "28.00" not in row[0], row[0]


def test_module_level_code_means_something_is_implemented(root):
    assert _placeholder_only(root, "def later():\n    pass\n\n\nprint(len([1, 2]))\n") is False


def test_not_implemented_stubs_are_placeholders(root):
    source = "def load():\n    raise NotImplementedError\n\n\ndef save():\n    raise NotImplementedError('soon')\n"
    assert _placeholder_only(root, source) is True


def test_a_constants_only_module_is_not_placeholder_only(root):
    assert _placeholder_only(root, "LIMIT = 10\nNAMES = ('a', 'b')\n") is False


def test_cached_results_from_before_the_metadata_boundary_are_not_reused():
    from slop_detector.analysis_cache import CACHE_ENGINE_VERSION

    assert CACHE_ENGINE_VERSION not in {f"analysis-cache-v{n}" for n in range(11, 19)}
