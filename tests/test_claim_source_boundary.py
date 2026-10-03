"""Claim-source boundary (P1-4 step A): a jargon claim is prose, not code.

A word inside a comment or a string literal (docstrings, log and error
messages) is a claim. The same word inside an import path, an attribute path,
or an identifier is code: `torch.distributed`, `from x.distributed import y`,
and `distributed_client` claim nothing.

Fixture docstrings are multi-line because a one-line docstring is still skipped
by the scan (a separate, deferred coverage fix), and fixtures live under a
directory whose path contains no "test_".
"""

from __future__ import annotations

import textwrap
from pathlib import Path
from typing import List

import pytest

from slop_detector.core import SlopDetector
from slop_detector.metrics import inflation


@pytest.fixture
def root(tmp_path_factory):
    return tmp_path_factory.mktemp("proj")


def _write(root: Path, source: str) -> Path:
    path = root / "m.py"
    path.write_text(textwrap.dedent(source).lstrip("\n"), encoding="utf-8")
    return path


def _jargon_words(path: Path) -> List[str]:
    analysis = SlopDetector(read_only=True).analyze_file(str(path))
    return [d["word"] for d in analysis.inflation.jargon_details]


def test_import_path_is_not_a_claim(root):
    path = _write(
        root,
        """
        from lmcache.v1.distributed.api import ObjectKey
        import torch.distributed as dist


        def f(key):
            return ObjectKey(key), dist
        """,
    )
    assert "distributed" not in _jargon_words(path)


def test_attribute_path_and_identifier_are_not_claims(root):
    path = _write(
        root,
        """
        import torch


        def group(config):
            config.distributed = True
            scalable = config.scalable
            distributed_client = None
            return torch.distributed.ProcessGroup, scalable, distributed_client
        """,
    )
    words = _jargon_words(path)
    assert "distributed" not in words and "scalable" not in words, words


def test_comment_claim_is_still_detected(root):
    path = _write(
        root,
        """
        # A distributed, scalable scheduler.
        def f(x):
            return x
        """,
    )
    words = _jargon_words(path)
    assert "distributed" in words and "scalable" in words, words


def test_multiline_docstring_and_message_claims_are_still_detected(root):
    path = _write(
        root,
        '''
        import logging


        def start():
            """Start the service.

            Production-ready startup path.
            """
            logging.info("distributed cache ready")
        ''',
    )
    words = _jargon_words(path)
    assert "production-ready" in words and "distributed" in words, words


def test_one_line_docstring_coverage_is_unchanged_in_p1_4(root):
    """Deferred, not fixed here: a one-line docstring is still skipped by the scan."""
    path = _write(
        root,
        '''
        def serve(x):
            """Production-ready service."""
            return x
        ''',
    )
    assert "production-ready" not in _jargon_words(path)


def test_file_without_a_jargon_candidate_is_not_tokenized(root, monkeypatch):
    """Cost: tokenizing is deferred until a candidate is found (at most once per file)."""
    calls = []
    real = inflation._prose_spans

    def counting(content):
        calls.append(1)
        return real(content)

    monkeypatch.setattr(inflation, "_prose_spans", counting)
    plain = _write(root, "def f(x):\n    return x\n")
    assert _jargon_words(plain) == []
    assert calls == []

    claims = _write(root, "# A distributed, scalable, robust scheduler.\ndef f(x):\n    return x\n")
    assert len(_jargon_words(claims)) == 3
    assert calls == [1]


def test_cached_results_from_before_the_boundary_are_not_reused():
    """Findings changed, so results cached by an older engine must be recomputed."""
    from slop_detector.analysis_cache import CACHE_ENGINE_VERSION

    assert CACHE_ENGINE_VERSION not in {f"analysis-cache-v{n}" for n in (11, 12, 13)}
