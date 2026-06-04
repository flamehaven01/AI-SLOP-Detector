# External Architecture Absorption Report

This report captures what was worth learning from a high-performing external
code-health engine and translates it into internal upgrade language for
`AI-SLOP-DETECTOR`.

---

## 1. What Was Extracted

The external study exposed five mechanics with direct upgrade value:

| Mechanic | Why It Matters Here |
| :--- | :--- |
| metadata-aware caching | removes repeated full-file recomputation |
| deterministic changed-file filtering | narrows scans to what actually moved |
| inline suppression rules | lowers false-positive friction without global config edits |
| churn-aware prioritization | raises urgency on unstable, frequently touched files |
| agent-facing interfaces | makes the engine queryable by tools and assistants |

The useful lesson was not branding, but execution discipline: fast paths,
deterministic filtering, and operational ergonomics were treated as first-class
features rather than afterthoughts.

---

## 2. Internal Relevance

`AI-SLOP-DETECTOR` already has strong mathematical governance and multi-axis
scoring. The main opportunity is operational hardening:

- reduce repeated work on large project scans
- avoid quadratic structural-analysis blowups
- lower developer friction when exceptions are intentional
- prioritize findings based on change pressure, not only static severity

---

## 3. High-Value Capability Seeds

The external study yielded these concrete seeds:

| Seed | Internal Target |
| :--- | :--- |
| metadata invalidation on cache drift | `src/slop_detector/caching/` |
| repo-root aware path normalization | project scan and changed-file filtering |
| inline suppression parsing | `src/slop_detector/parser/` or adjacent core path |
| interval-based duplicate filtering | clone and cross-file dedupe analysis |
| changed-file aware result filtering | CLI and CI report shaping |

---

## 4. What Has Started

The first absorbed change is underway now:

- structural topology scaling via an exact ceiling
- deterministic approximation above that ceiling
- explicit result labeling so consumers know when approximation was used

This is the right first move because it directly protects large-project scans
from the most obvious algorithmic cost spike.
