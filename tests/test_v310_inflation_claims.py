"""v3.10 inflation counts claims, not the vocabulary of the domain.

Found on NSRW / Flamehaven-TOE / RExSyn and measured on 17 repositories
(non-test Python): the jargon list mixed technical nouns with claim words.
Hits per word (unjustified): embedding 316 (204), optimization 156 (156),
transformer 136 (63), neural 53 (42), distributed 39 (37), equation 33 (33),
serverless 19 (19); sampled hits are descriptions ("loop-index embedding",
"Henderson Hasselbalch equation", "As an optimization ...", "rank within the
distributed job"). A number-theory "complex embedding" counted as ML jargon.
The claim judge (context_jargon) also kept an evidence rule for "advanced"
that inflation never emits (it emits "advanced algorithm"), so that rule
never ran.

Contract:
- inflation counts claim words only: quality and scale qualifiers
  (robust, comprehensive, optimized, state-of-the-art, production-ready,
  scalable, ...) and venue names; technical nouns are not inflation;
- every evidence rule names a counted claim word, and every justification
  category has words to justify (one vocabulary for both judges).
"""

from __future__ import annotations

import ast
import textwrap

from slop_detector.config import Config
from slop_detector.metrics.context_jargon import ContextJargonDetector
from slop_detector.metrics.inflation import InflationCalculator


def _jargon(source: str) -> list:
    source = textwrap.dedent(source)
    result = InflationCalculator(Config()).calculate("mod.py", source, ast.parse(source))
    return sorted(result.jargon_found)


def test_technical_nouns_are_not_inflation():
    source = """
        # fraction of channels receiving loop-index embedding
        # Henderson Hasselbalch equation: pH = pKa + log([A-]/[HA])
        # As an optimization when repeatedly asked to look up the same record
        # rank of this process within the distributed job
        # decoding of neural language models with a transformer block
        # deployable as a serverless function on microservices
        def total(values):
            return sum(values)
        """
    assert _jargon(source) == []


def test_claim_words_are_still_counted():
    source = """
        # A robust, comprehensive and production-ready state-of-the-art solver
        # (NeurIPS spotlight) built on an advanced algorithm
        def total(values):
            return sum(values)
        """
    assert _jargon(source) == [
        "advanced algorithm",
        "comprehensive",
        "neurips",
        "production-ready",
        "robust",
        "spotlight",
        "state-of-the-art",
    ]


def test_every_evidence_rule_names_a_counted_claim_word():
    claims = {word for words in InflationCalculator.JARGON.values() for word in words}
    assert set(ContextJargonDetector.EVIDENCE_REQUIREMENTS) <= claims


def test_every_justification_category_has_claim_words():
    assert set(InflationCalculator.JUSTIFICATIONS) <= set(InflationCalculator.JARGON)


def test_advanced_algorithm_claim_is_checked_for_evidence():
    source = textwrap.dedent(
        """
        # Uses an advanced algorithm for ranking.
        def rank(values):
            return sorted(values)
        """
    )
    tree = ast.parse(source)
    config = Config()
    inflation = InflationCalculator(config).calculate("mod.py", source, tree)
    result = ContextJargonDetector(config).analyze("mod.py", source, tree, inflation)
    assert [e.jargon for e in result.evidence_details] == ["advanced algorithm"]
