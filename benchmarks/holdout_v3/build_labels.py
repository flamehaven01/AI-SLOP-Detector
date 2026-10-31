"""Freeze the hold-out v3 labels (PROTOCOL.md section 5) into labels.json. No detector runs.

Joins the drawn samples (sample.json, sample_replacement.json, sample_reserves.json)
with the labeler's draft files (`ID LABEL [STATIC|SEMANTIC] | note`, one per line)
and the selection record (repos.json: tier, AI signal). Every drawn function must
have exactly one label and every label a drawn function, or nothing is written.

usage: python -P benchmarks/holdout_v3/build_labels.py --drafts DRAFT_DIR
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
LINE = re.compile(r"(T\d{3,4}) (\S+)(?: (STATIC|SEMANTIC))?(?: \| (.*))?$")
CLASSES = {
    "GENUINE", "UNCLEAR", "STUB_DISGUISED", "FAILURE_AS_SUCCESS", "CLAIM_WITHOUT_MECHANISM",
    "IGNORED_INPUT", "ALWAYS_PASS_CHECK", "HARDCODED_RESULT", "PLACEHOLDER_PLAIN",
}


def _samples() -> tuple[list, dict]:
    rows, meta = [], {}
    for name in ("sample.json", "sample_replacement.json", "sample_reserves.json"):
        path = HERE / name
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            rows += data["sample"]
            meta.update(data["meta"]["repos"])
    return rows, meta


def _drafts(directory: Path) -> tuple[dict, str]:
    labels, digest = {}, hashlib.sha256()
    for path in sorted(directory.glob("v3labels_*.txt")):
        digest.update(path.read_bytes())
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            match = LINE.match(line.strip())
            if not match or match.group(2) not in CLASSES:
                raise SystemExit(f"{path.name}: bad label line {line!r}")
            fid, label, evidence, note = match.groups()
            if fid in labels:
                raise SystemExit(f"{fid}: labeled twice")
            if (label not in ("GENUINE", "UNCLEAR")) != bool(evidence):
                raise SystemExit(f"{fid}: a hollow label needs STATIC or SEMANTIC evidence, others none")
            labels[fid] = {"label": label, "evidence": evidence, "note": note or ""}
    return labels, digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--drafts", required=True)
    args = parser.parse_args()
    rows, repo_meta = _samples()
    labels, drafts_sha = _drafts(Path(args.drafts))
    ids = {r["id"] for r in rows}
    if ids != set(labels):
        raise SystemExit(
            f"unlabeled {sorted(ids - set(labels))[:5]}, unknown {sorted(set(labels) - ids)[:5]}"
        )
    signals = {
        p["repo"]: p["signal"]
        for p in json.loads((HERE / "repos.json").read_text(encoding="utf-8"))["repos"]
    }
    functions = []
    for r in sorted(rows, key=lambda x: x["id"]):
        m = repo_meta[r["repo"]]
        signal = signals.get(r["repo"])
        functions.append(
            {
                "id": r["id"],
                "tier": r["tier"],
                "stratum": r["stratum"],
                "repo": r["repo"],
                "dir": m["dir"],
                "head": m["head"],
                "dirty": m["dirty"],
                "file": r["file"],
                "file_sha256": m["file_sha256"][r["file"]],
                "function": r["function"],
                "span": r["span"],
                "sha256": r["sha256"],
                **labels[r["id"]],
                "ai_signal": None
                if not signal
                else {
                    "instruction_file": bool(signal["instruction_files"]),
                    "co_author_trailer": bool(signal["co_author_trailers"]),
                },
            }
        )
    v2_meta = json.loads((HERE.parent / "holdout_v2" / "labels.json").read_text("utf-8"))["meta"]
    meta = {
        "protocol": "benchmarks/holdout_v3/PROTOCOL.md",
        "protocol_sha256": hashlib.sha256((HERE / "PROTOCOL.md").read_bytes()).hexdigest(),
        "seed": "holdout-v3-20261030",
        "labeler": "rule author (Claude), blind: labels fixed and committed before the frozen "
        "detector ran on these repositories",
        "blinding": "functions shown in a seeded shuffled order with tier and stratum hidden; "
        "repository names were visible (needed to judge fixed signatures)",
        "display": v2_meta["display"],
        "rules": v2_meta["rules"],
        "classes": json.loads((HERE.parent / "holdout" / "labels.json").read_text("utf-8"))[
            "meta"
        ]["classes"],
        "evidence": {
            "STATIC": "a line-level fact confirms the hollow label",
            "SEMANTIC": "the hollow label needs the meaning of names or docstrings",
        },
        "replacements": [
            {
                "primary": "kumaran-is/claude-code-onboarding",
                "by": "toon-format/toon-python",
                "reason": "all 39 .py files sit under .claude/, which the product's discovery "
                "skips: 0 functions to draw",
            }
        ],
        "reserves": "the AI_ASSOCIATED primaries gave 2 hollow labels (< 30), so the remaining "
        "AI_ASSOCIATED reserves were drawn and labeled in walk order, before any scan",
        "drafts_sha256": drafts_sha,
    }
    out = {"meta": meta, "functions": functions}
    (HERE / "labels.json").write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n", "utf-8", newline="\n")
    counts = {}
    for f in functions:
        key = f"{f['tier']}/{'hollow' if f['label'] not in ('GENUINE', 'UNCLEAR') else f['label']}"
        counts[key] = counts.get(key, 0) + 1
    print(len(functions), "functions", counts)
    return 0


if __name__ == "__main__":
    sys.exit(main())
