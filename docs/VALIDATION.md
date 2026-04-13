# Validation & External Benchmarking

## Current Status

AI-SLOP-Detector has not been independently validated.

The scoring model (geometric mean aggregation, AST distribution fingerprinting,
structural coherence) is mathematically coherent and deterministic. The design
decisions are reasoned. But "reasoned design" is not the same as "empirically
validated."

Internal self-testing — running the tool on its own codebase, or on hand-crafted
test fixtures — does not constitute validation. The benchmark artifacts and the
tool share the same author, the same assumptions, and the same definition of what
"slop" looks like. That circularity cannot be resolved from the inside.

---

## What Independent Validation Requires

**1. External institution**
An organization with no stake in the outcome: a university research group,
an independent software quality lab, or an open-source community effort.
Not affiliated with Flamehaven.

**2. Independent system environment**
The evaluation must be designed without Flamehaven's internal ontology
(CQMS, SIDRCE, Omega scoring, etc.) shaping the methodology. Internal
frameworks create blind spots — concepts that look rigorous within the
framework but have not been tested against alternatives.

**3. Reproducible, deterministic evaluation engine**
The tool already satisfies this: given the same input file, it produces
the same output on any machine. This is a prerequisite, not a claim.

**4. Peer review**
Reviewers with expertise in static analysis, software quality measurement,
or ML-based code evaluation — who are willing to challenge the methodology,
not just verify the arithmetic.

**5. Published results including failures**
Any publication must include cases where the tool underperformed, produced
false positives, or where the v3.5.0 changes made no measurable difference
compared to v3.4.0. Reporting only positive results is its own form of
distortion.

---

## What We Do Not Yet Know

- Whether geometric mean aggregation produces fewer false positives than
  arithmetic mean on real-world codebases outside the development environment.
- Whether the AST node type distribution is a meaningful signal for detecting
  AI-generated code, or whether it correlates with confounds (file size,
  module type, coding style) more than with AI authorship.
- Whether structural coherence (MST max-edge distance between file distributions)
  distinguishes AI-scaffolded from human-written code at a rate better than
  a simpler baseline.

These are open questions. They are listed here so that users and potential
contributors know what has and has not been claimed.

---

## Contributing to Validation

If you are interested in running an independent evaluation:

- The tool is deterministic and CLI-driven: `slop-detector --project ./src --json`
- JSON output includes all intermediate scores (LDR, inflation, DDC, pattern counts,
  structural coherence, per-file DCF) for external analysis
- A labeled dataset of AI-generated vs. human-written Python files would allow
  direct measurement of precision and recall
- Comparison against other static analysis tools (pylint, flake8, radon) on the
  same dataset would establish whether the tool adds signal beyond existing tools

Open an issue on GitHub if you are running such an evaluation. We will not
pre-announce results we do not have.
