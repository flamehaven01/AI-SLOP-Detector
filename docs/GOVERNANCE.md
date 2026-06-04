# Governance Verification

This document defines the artifact contract and enforcement boundary for
`slop-detector verify-governance`.

---

## Purpose

The governance layer is intentionally separate from the scoring model.

- The scoring path computes deficits, topology, and hotspot ranking.
- The governance path verifies that the record written for a run is intact and
  policy-compliant.

This separation keeps math changes from implicitly changing CI policy.

---

## Artifact Contract

The verification command reads:

- `.cr-ep/governance_record.json`

It expects the record to contain:

- `record_hash`
- `counts.halt_count`
- `trust_tier`
- the durable session identity and comparability fields

The hash is recomputed canonically from the record with volatile timestamps
removed. A mismatch indicates tampering or record drift.

---

## Enforcement Rules

`slop-detector verify-governance` fails closed when any of the following is
true:

- the record cannot be read
- `record_hash` is missing
- the recomputed hash does not match the stored hash
- `counts.halt_count > 0`
- `trust_tier == "UNTRUSTED"`

On success the command exits `0`. On failure it exits `1`.

---

## Usage

```bash
slop-detector verify-governance ./.cr-ep
```

You can also point it directly at the record file:

```bash
slop-detector verify-governance .cr-ep/governance_record.json
```

---

## Relation To Mathematical Models

The mathematical model documentation lives in [MATH_MODELS.md](MATH_MODELS.md).
That document covers the scoring and snapshot audit boundary. This document
covers the enforcement gate that consumes the record.

