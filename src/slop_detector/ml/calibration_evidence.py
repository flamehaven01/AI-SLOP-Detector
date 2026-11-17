"""Where a judgment about a finding comes from, and how much it is worth.

Between two comparable runs of one file (same project root, same measurement
fingerprint), a rule that fired in the first run gets at most one state:

- VERIFIED_FIX: the file changed and the rule stopped firing while it was
  measured (no pattern error), not suppressed, not masked and not ignored.
  The warning was resolved under the same measurement; that does not prove
  the code works.
- UNCHANGED_WARNING: it fires again on the same bytes. Nobody acted on it;
  that is not a false positive.
- USER_SUPPRESSED_UNVERIFIED: a plain `# slop-disable` hides it. The user may
  have judged it wrong, or accepted the risk.
- USER_DECLARED_FALSE_POSITIVE: an `fp:` declaration hides it. The user says
  it is a false positive; nothing verified that.

No state is a learning label (3.16.2): they are reported beside the weights
search, which still learns from its metric-only labels. A state is bound to
the hash of the bytes it was observed on; the reason of a declaration is kept
only as its SHA-256.

ASCII-only (cp949 safety).
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Mapping, Optional

from slop_detector.models import DECLARED_FALSE_POSITIVE

VERIFIED_FIX = "verified_fix"
UNCHANGED_WARNING = "unchanged_warning"
USER_SUPPRESSED_UNVERIFIED = "user_suppressed_unverified"
USER_DECLARED_FALSE_POSITIVE = DECLARED_FALSE_POSITIVE
STATES = (VERIFIED_FIX, UNCHANGED_WARNING, USER_SUPPRESSED_UNVERIFIED, USER_DECLARED_FALSE_POSITIVE)


def withheld_evidence(file_analysis: Any) -> Dict[str, list]:
    """What a scan of one file held back from its findings, rule by rule:
    suppressed (with the user's kind of judgment), unmeasured (the pattern
    raised), masked (framework masking) and ignored (`@slop.ignore`)."""
    suppressed = []
    for entry in getattr(file_analysis, "suppression_ledger", None) or []:
        item: Dict[str, Any] = {
            "rule": entry.pattern_id,
            "line": entry.suppressed_line,
            "state": (
                USER_DECLARED_FALSE_POSITIVE
                if getattr(entry, "declared_false_positive", False)
                else USER_SUPPRESSED_UNVERIFIED
            ),
        }
        if item["state"] == USER_DECLARED_FALSE_POSITIVE:
            item["reason_sha256"] = entry.reason_sha256
        suppressed.append(item)
    errors = getattr(file_analysis, "pattern_errors", None) or []
    masked = getattr(file_analysis, "masked_issues", None) or []
    ignored = getattr(file_analysis, "ignored_functions", None) or []
    return {
        "suppressed": suppressed,
        "unmeasured": sorted({str(e.get("pattern_id")) for e in errors}),
        "masked": sorted({m.pattern_id for m in masked}),
        "ignored": sorted({rule for f in ignored for rule in (f.rules or ["all"])}),
    }


def _load(value: Any) -> Any:
    return json.loads(value) if isinstance(value, str) else value


def classify_pair(now: Mapping[str, Any], nxt: Mapping[str, Any]) -> List[Dict[str, Any]]:
    """One record per rule that fired in `now` and has a state in `nxt`.

    A row is {file_hash, fired_rules ({rule: count} or its JSON), withheld
    (withheld_evidence, its JSON, or None for a row recorded before 3.16.2)}.
    Without a withheld record nothing can be shown about the next run, so only
    UNCHANGED_WARNING (which needs none) is given."""
    fired_now = _load(now.get("fired_rules")) or {}
    fired_next = _load(nxt.get("fired_rules")) or {}
    withheld: Optional[Dict[str, list]] = _load(nxt.get("withheld"))
    changed = now.get("file_hash") != nxt.get("file_hash")
    suppressed = _suppressions(withheld)
    records = []
    for rule in sorted(fired_now):
        state = _state(rule, fired_next, withheld, changed, suppressed)
        if state is None:
            continue
        record: Dict[str, Any] = {"rule": rule, "file_hash": nxt.get("file_hash"), "state": state}
        if rule in suppressed:
            record["line"] = suppressed[rule]["line"]
            if "reason_sha256" in suppressed[rule]:
                record["reason_sha256"] = suppressed[rule]["reason_sha256"]
        records.append(record)
    return records


def _suppressions(withheld: Optional[Mapping[str, list]]) -> Dict[str, Dict[str, Any]]:
    """The suppression that stands for each rule: a declaration on any of its
    lines is the user's judgment for the rule."""
    suppressed: Dict[str, Dict[str, Any]] = {}
    for item in (withheld or {}).get("suppressed", []):
        if item["rule"] not in suppressed or item["state"] == USER_DECLARED_FALSE_POSITIVE:
            suppressed[item["rule"]] = item
    return suppressed


def _state(
    rule: str,
    fired_next: Mapping[str, Any],
    withheld: Optional[Mapping[str, list]],
    changed: bool,
    suppressed: Mapping[str, Mapping[str, Any]],
) -> Optional[str]:
    if rule in suppressed:
        return str(suppressed[rule]["state"])
    if rule in fired_next:
        return None if changed else UNCHANGED_WARNING
    if changed and withheld is not None and _was_looked_at(rule, withheld):
        return VERIFIED_FIX
    return None


def _was_looked_at(rule: str, withheld: Mapping[str, list]) -> bool:
    if rule in withheld.get("unmeasured", []) or rule in withheld.get("masked", []):
        return False
    ignored = withheld.get("ignored", [])
    return rule not in ignored and "all" not in ignored
