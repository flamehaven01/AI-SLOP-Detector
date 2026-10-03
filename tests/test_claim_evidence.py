"""RED corpus for claim evidence (P1-4): shallow signals are not evidence.

Two paths judge whether a quality claim ("scalable", "production-ready", ...) is
backed by code:

- the score path: InflationCalculator subtracts justified jargon from the
  inflation score, so a spoofed justification lowers deficit_score;
- the report path: ContextJargonDetector lists evidence per claim, read by the
  CI gate (--ci-claims-strict), the question generator, and the reports.

Contract:
- evidence states: structural (seen in code structure), weak (text or name hint
  only), absent (measured, not there), unmeasured (no collector at this scope);
- a claim's support_level: structural | weak | unsupported | unmeasured, and
  is_justified is true only when support is structural (it never means the
  claim is true);
- comments, string literals, identifier names, class names, and complexity
  alone never count as structural evidence; neither does the claim word itself;
- test evidence is file-local here, so for a non-test file it is unmeasured,
  never confirmed missing.
"""

from __future__ import annotations

import ast
import textwrap
from pathlib import Path
from typing import Dict, List

import pytest

from slop_detector.core import SlopDetector
from slop_detector.metrics.context_jargon import ContextJargonDetector

STATES = {"structural", "weak", "absent", "unmeasured"}
LEVELS = {"structural", "weak", "unsupported", "unmeasured"}


@pytest.fixture
def root(tmp_path_factory):
    """A project root (it has a marker, so path facts are relative to it).

    Its path contains no "test_" (see module docstring), and the marker makes
    `tests/integration/...` a directory fact rather than unknown.
    """
    proj = tmp_path_factory.mktemp("proj")
    (proj / "pyproject.toml").write_text("[project]\nname = 'fixture'\n", encoding="utf-8")
    return proj


def _write(root: Path, rel: str, source: str) -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(source).lstrip("\n"), encoding="utf-8")
    return path


def _analyze(path: Path):
    return SlopDetector(read_only=True).analyze_file(str(path))


def _justified(analysis, word: str) -> List[bool]:
    """Score-path verdicts for every occurrence of `word`."""
    hits = [d["justified"] for d in analysis.inflation.jargon_details if d["word"] == word]
    assert hits, f"jargon {word!r} not detected; fixture is blind"
    return hits


def _claim(analysis, word: str):
    """Report-path evidence for the first occurrence of claim `word`."""
    details = [e for e in analysis.context_jargon.evidence_details if e.jargon == word]
    assert details, f"claim {word!r} not evaluated; fixture is blind"
    return details[0]


def _field(claim, name: str):
    """A new claim field, or an assertion failure (not AttributeError) on old code."""
    assert hasattr(claim, name), f"JargonEvidence has no {name!r}"
    return getattr(claim, name)


def _states(path: Path) -> Dict[str, str]:
    detector = ContextJargonDetector(SlopDetector(read_only=True).config)
    assert hasattr(detector, "evidence_states"), "ContextJargonDetector.evidence_states missing"
    source = path.read_text(encoding="utf-8")
    states = detector.evidence_states(source, ast.parse(source), str(path))
    assert set(states.values()) <= STATES, set(states.values())
    return states


# ---------------------------------------------------------------------------
# Score path: only code structure justifies jargon
# ---------------------------------------------------------------------------


def test_comment_mentioning_a_library_does_not_justify(root):
    path = _write(
        root,
        "m.py",
        '''
        def handler(items):
            """Fixture.

            Scalable fan-out handler.
            """
            # asyncio would make this scalable
            return [i for i in items]
        ''',
    )
    assert _justified(_analyze(path), "scalable") == [False, False]


def test_string_literal_naming_a_library_does_not_justify(root):
    path = _write(
        root,
        "m.py",
        '''
        def handler(items):
            """Fixture.

            Scalable fan-out handler.
            """
            mode = "asyncio"
            return [mode for _ in items]
        ''',
    )
    assert _justified(_analyze(path), "scalable") == [False]


def test_identifier_containing_a_library_name_does_not_justify(root):
    path = _write(
        root,
        "m.py",
        '''
        def handler(items):
            """Fixture.

            Scalable fan-out handler.
            """
            asyncio_mode = 1
            return [asyncio_mode for _ in items]
        ''',
    )
    assert _justified(_analyze(path), "scalable") == [False]


def test_the_claim_word_does_not_justify_itself(root):
    """'distributed' was both jargon and a justifier, so it always justified itself."""
    path = _write(
        root,
        "m.py",
        '''
        def lookup(key, table):
            """Fixture.

            A distributed cache lookup.
            """
            return table.get(key)
        ''',
    )
    assert _justified(_analyze(path), "distributed") == [False]


def test_preservation_real_async_usage_justifies(root):
    path = _write(
        root,
        "m.py",
        '''
        import asyncio


        async def fan_out(jobs):
            """Fixture.

            Scalable fan-out.
            """
            return await asyncio.gather(*jobs)
        ''',
    )
    assert _justified(_analyze(path), "scalable") == [True]


def test_aliased_import_usage_justifies(root):
    """Structural use through an alias (text search for 'torch' missed `T.nn`)."""
    path = _write(
        root,
        "m.py",
        '''
        import torch as T


        def build(n):
            """Fixture.

            Neural layer.
            """
            return T.nn.Linear(n, n)
        ''',
    )
    assert _justified(_analyze(path), "neural") == [True]


def test_preservation_cache_decorator_justifies(root):
    path = _write(
        root,
        "m.py",
        '''
        from functools import lru_cache


        @lru_cache(maxsize=None)
        def fib(n):
            """Fixture.

            Optimized fibonacci.
            """
            return n if n < 2 else fib(n - 1) + fib(n - 2)
        ''',
    )
    assert _justified(_analyze(path), "optimized") == [True]


def test_module_import_outside_the_function_does_not_justify_function_jargon(root):
    """Preservation of the function scope: the library must be used where the claim is."""
    path = _write(
        root,
        "m.py",
        '''
        import asyncio


        def handler(items):
            """Fixture.

            Scalable fan-out handler.
            """
            return list(items)


        async def other():
            await asyncio.sleep(0)
        ''',
    )
    assert _justified(_analyze(path), "scalable") == [False]


# ---------------------------------------------------------------------------
# Report path: evidence states
# ---------------------------------------------------------------------------


def test_keywords_in_comments_are_weak_not_structural(root):
    path = _write(
        root,
        "service.py",
        """
        # token cache metrics config prometheus redis auth retry optimize isinstance ValueError
        def serve(x):
            return x
        """,
    )
    states = _states(path)
    keys = ("security", "caching", "monitoring", "config_management", "retry_logic")
    for key in keys + ("input_validation",):
        assert states[key] == "weak", (key, states[key])


def test_class_name_alone_is_not_a_design_pattern(root):
    path = _write(
        root,
        "m.py",
        """
        class EnterpriseSingletonFactory:
            value = 1
        """,
    )
    assert _states(path)["design_patterns"] == "weak"


def test_complexity_alone_is_not_an_advanced_algorithm(root):
    branches = "".join(f"    if x == {i}:\n        return {i}\n" for i in range(12))
    path = _write(root, "m.py", "def f(x):\n" + branches + "    return -1\n")
    assert _states(path)["advanced_algorithms"] == "unmeasured"


def test_requirements_without_a_collector_are_unmeasured(root):
    path = _write(root, "m.py", "def f(x):\n    return x\n")
    states = _states(path)
    for key in (
        "connection_pooling",
        "rate_limiting",
        "circuit_breaker",
        "fallback",
        "profiling",
        "memoization",
        "lazy_loading",
        "algorithmic_efficiency",
        "error_messages",
        "abstraction",
        "modularity",
    ):
        assert states[key] == "unmeasured", (key, states[key])


def test_structural_collectors_still_see_structure(root):
    """Preservation: real try/except, logging calls, validation, and async are structural."""
    path = _write(
        root,
        "m.py",
        """
        import logging

        log = logging.getLogger(__name__)


        async def handle(value):
            if not isinstance(value, int):
                raise ValueError("value must be an int")
            try:
                return value * 2
            except OverflowError:
                log.error("overflow")
                raise
        """,
    )
    states = _states(path)
    for key in ("error_handling", "logging", "input_validation", "async_support"):
        assert states[key] == "structural", (key, states[key])


# ---------------------------------------------------------------------------
# Test evidence is file-local: never "confirmed missing" for a source file
# ---------------------------------------------------------------------------


def test_source_file_test_evidence_is_unmeasured_not_missing(root):
    """The falsifier: real integration tests exist in another file the detector cannot see."""
    src = _write(
        root,
        "src/service.py",
        '''
        def serve(x):
            """Fixture.

            Production-ready service.
            """
            return x
        ''',
    )
    _write(
        root,
        "tests/integration/test_service.py",
        """
        from service import serve


        def test_serve_round_trip():
            assert serve(1) == 1
        """,
    )
    claim = _claim(_analyze(src), "production-ready")
    assert "tests_integration" not in claim.missing_evidence
    assert "tests_integration" in _field(claim, "unmeasured_evidence")
    assert "tests_unit" in _field(claim, "unmeasured_evidence")


def test_a_test_in_the_directory_name_does_not_make_a_source_file_a_test(root):
    """Only the file itself (test_*.py, *_test.py, or a tests/ parent) makes it a test file."""
    path = _write(root, "my_test_project/src/service.py", "def serve(x):\n    return x\n")
    states = _states(path)
    assert states["tests_unit"] == "unmeasured"
    assert states["tests_integration"] == "unmeasured"


def test_test_file_test_evidence_is_measured(root):
    path = _write(
        root,
        "tests/integration/test_flow.py",
        '''
        def test_flow():
            """Fixture.

            Production-ready flow check.
            """
            assert 1 + 1 == 2
        ''',
    )
    assert _states(path)["tests_integration"] == "structural"


# ---------------------------------------------------------------------------
# Claim-level support
# ---------------------------------------------------------------------------


def test_keyword_only_production_claim_is_not_justified(root):
    path = _write(
        root,
        "service.py",
        '''
        # config settings yaml json token auth metric cache
        def serve(x):
            """Fixture.

            Production-ready service.
            """
            return x
        ''',
    )
    claim = _claim(_analyze(path), "production-ready")
    assert _field(claim, "support_level") == "weak"
    assert claim.is_justified is False
    assert "config_management" in _field(claim, "weak_evidence")
    assert "config_management" not in claim.found_evidence


def test_logging_alone_does_not_justify_production_ready(root):
    path = _write(
        root,
        "service.py",
        '''
        import logging

        log = logging.getLogger(__name__)


        def serve(x):
            """Fixture.

            Production-ready service.
            """
            log.info("serving")
            return x
        ''',
    )
    claim = _claim(_analyze(path), "production-ready")
    assert claim.found_evidence == ["logging"]
    assert claim.is_justified is False


def test_async_def_alone_does_not_justify_scalable(root):
    path = _write(
        root,
        "m.py",
        '''
        async def handler(items):
            """Fixture.

            Scalable handler.
            """
            return list(items)
        ''',
    )
    claim = _claim(_analyze(path), "scalable")
    assert claim.is_justified is False
    assert _field(claim, "support_level") in {"weak", "unsupported"}


def test_structural_evidence_justifies_robust(root):
    path = _write(
        root,
        "m.py",
        '''
        def parse(value):
            """Fixture.

            Robust integer parser.
            """
            if not isinstance(value, str):
                raise TypeError("value must be a str")
            try:
                return int(value)
            except ValueError:
                return None
        ''',
    )
    claim = _claim(_analyze(path), "robust")
    assert _field(claim, "support_level") == "structural"
    assert claim.is_justified is True
    assert set(claim.found_evidence) == {"error_handling", "input_validation"}


def test_claim_with_no_measurable_requirement_is_unmeasured(root):
    """'sophisticated' needs design_patterns, abstraction, modularity: none structural here."""
    path = _write(
        root,
        "m.py",
        '''
        def f(x):
            """Fixture.

            Sophisticated helper.
            """
            return x
        ''',
    )
    claim = _claim(_analyze(path), "sophisticated")
    assert claim.is_justified is False
    assert _field(claim, "support_level") in {"unsupported", "unmeasured"}


def test_every_claim_reports_a_consistent_level(root):
    path = _write(
        root,
        "m.py",
        '''
        # metrics cache auth
        def f(x):
            """Fixture.

            Production-ready, scalable, robust, resilient, optimized helper.
            """
            return x
        ''',
    )
    details = _analyze(path).context_jargon.evidence_details
    assert details
    for claim in details:
        assert _field(claim, "support_level") in LEVELS, _field(claim, "support_level")
        assert claim.is_justified == (_field(claim, "support_level") == "structural")
        listed = set(claim.found_evidence) | set(_field(claim, "weak_evidence"))
        listed |= set(claim.missing_evidence) | set(_field(claim, "unmeasured_evidence"))
        assert listed == set(claim.required_evidence), claim.jargon
        payload = claim.to_dict()
        for key in ("support_level", "weak_evidence", "unmeasured_evidence"):
            assert key in payload, key


# ---------------------------------------------------------------------------
# CI gate: strict mode keeps failing an uncovered production claim
# ---------------------------------------------------------------------------


def test_strict_gate_still_fails_a_production_claim_without_test_evidence(root):
    """PRESERVATION: moving tests_integration to unmeasured must not make the gate pass."""
    from slop_detector.ci_gate import CIGate

    path = _write(
        root,
        "src/service.py",
        '''
        def serve(x):
            """Fixture.

            Production-ready service.
            """
            return x
        ''',
    )
    analysis = _analyze(path)
    gate = CIGate(claims_strict=True)
    assert gate._has_uncovered_production_claims(analysis.context_jargon) is True


@pytest.mark.parametrize("word", ["production-ready", "scalable"])
def test_strict_gate_passes_a_claim_backed_by_a_real_integration_test(root, word):
    """Acceptance for the gate: a test file with real integration tests is covered."""
    from slop_detector.ci_gate import CIGate

    path = _write(
        root,
        "tests/integration/test_flow.py",
        f'''
        def test_flow():
            """Fixture.

            {word} flow check.
            """
            assert 1 + 1 == 2
        ''',
    )
    gate = CIGate(claims_strict=True)
    assert gate._has_uncovered_production_claims(_analyze(path).context_jargon) is False


# ---------------------------------------------------------------------------
# Consumers: one production-claim vocabulary; unmeasured is not "missing"
# ---------------------------------------------------------------------------


def test_production_claim_vocabulary_is_shared():
    """The gate and the Markdown report used two copies of the same set."""
    from slop_detector import renderer_markdown
    from slop_detector.ci_gate import CIGate
    from slop_detector.metrics import context_jargon

    shared = getattr(context_jargon, "PRODUCTION_CLAIMS", None)
    assert shared, "context_jargon.PRODUCTION_CLAIMS missing"
    assert CIGate._PRODUCTION_CLAIMS is shared
    assert renderer_markdown._PRODUCTION_CLAIMS_CLI is shared


def test_review_questions_do_not_call_unmeasured_tests_missing(root):
    from slop_detector.question_generator import QuestionGenerator

    path = _write(
        root,
        "src/service.py",
        '''
        def serve(x):
            """Fixture.

            Production-ready service.
            """
            return x
        ''',
    )
    questions = [q.question for q in QuestionGenerator().generate_questions(_analyze(path))]
    claim = [q for q in questions if "'production-ready' claim" in q]
    assert claim, questions
    for text in claim:
        lacks = text.split("lacks:", 1)[1].split(".", 1)[0] if "lacks:" in text else ""
        assert "tests" not in lacks, text
    assert any("cannot be measured from this file" in q for q in claim), claim


def test_cached_results_from_before_evidence_hardening_are_not_reused():
    from slop_detector.analysis_cache import CACHE_ENGINE_VERSION

    assert CACHE_ENGINE_VERSION not in {f"analysis-cache-v{n}" for n in range(11, 16)}


def test_review_questions_keep_unmeasured_out_of_lacks_for_a_short_claim(root):
    """'robust' needs 3 things: 2 are absent, unit tests are unmeasured for a source file."""
    from slop_detector.question_generator import QuestionGenerator

    path = _write(
        root,
        "src/parse.py",
        '''
        def parse(value):
            """Fixture.

            Robust integer parser.
            """
            return int(value)
        ''',
    )
    questions = [q.question for q in QuestionGenerator().generate_questions(_analyze(path))]
    claim = [q for q in questions if "'robust' claim" in q]
    assert claim, questions
    assert "lacks: error handling, input validation." in claim[0], claim[0]
    assert "unit tests cannot be measured from this file" in claim[0], claim[0]
