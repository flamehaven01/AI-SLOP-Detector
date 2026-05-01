"""
LEDA Global Weight Injector — Flamehaven Sovereign Asset v1.0
=============================================================

PURPOSE:
    Harvests all Dogfooding calibration signals from Extra Repo targets,
    synthesizes the statistically optimal Global Default Weights,
    and injects them directly into the ai-slop-detector core engine source:
      - src/slop_detector/config.py  (DEFAULT_CONFIG + DOMAIN_PROFILES)
      - src/slop_detector/ml/self_calibrator.py  (fallback defaults)

ALGORITHM:
    1. HARVEST: Scan all slop_reports/leda_final.yaml across Extra Repo dirs.
    2. FILTER:  Retain entries with confidence_gap >= QUALITY_GATE *OR*
                highest-confidence entries if no target crosses the gate.
    3. SYNTHESIZE: Weighted average of optimal_weights, weighted by
                   improvement_events (more signal = more vote weight).
    4. VALIDATE: Ensure sum == 1.0, each dim in [MIN_W, MAX_W].
    5. INJECT:  Surgical regex rewrite of config.py + self_calibrator.py.
    6. REPORT:  Print a full summary + write injection_report.json.

USAGE:
    cd D:\\Sanctum\\ai-slop-detector
    .venv\\Scripts\\python.exe scripts\\global_injector.py [--dry-run] [--extra-repos PATH]

    --dry-run      : Show synthesis result without modifying any source files.
    --extra-repos  : Path to the Extra Repo root (default: D:\\Sanctum\\Extra Repo).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import yaml

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

QUALITY_GATE: float = 0.05       # confidence_gap threshold for "trusted" signal
MIN_IMPROVEMENT_EVENTS: int = 50  # minimum events to consider a repo's vote valid
MIN_W: float = 0.10               # minimum allowed weight per dimension
MAX_W: float = 0.65               # maximum allowed weight per dimension
DIMS = ("ldr", "inflation", "ddc", "purity")

ROOT = Path(__file__).resolve().parent.parent          # D:\Sanctum\ai-slop-detector
SRC_CONFIG = ROOT / "src" / "slop_detector" / "config.py"
SRC_CALIBRATOR = ROOT / "src" / "slop_detector" / "ml" / "self_calibrator.py"
DEFAULT_EXTRA_REPOS = Path(r"D:\Sanctum\Extra Repo")


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

class RepoSignal:
    """Calibration signal extracted from a single dogfooding target."""

    def __init__(self, repo: str, data: dict):
        self.repo = repo
        cal = data.get("calibration", {})
        self.status = cal.get("status", "unknown")
        self.improvement_events = cal.get("improvement_events", 0)
        self.fp_candidates = cal.get("fp_candidates", 0)
        self.confidence_gap = cal.get("confidence_gap", 0.0)
        raw_opt = cal.get("optimal_weights") or {}
        self.optimal_weights: Dict[str, float] = {d: float(raw_opt.get(d, 0.0)) for d in DIMS}
        self._normalize_weights()

    def _normalize_weights(self) -> None:
        total = sum(self.optimal_weights.values())
        if total > 0:
            for d in DIMS:
                self.optimal_weights[d] = round(self.optimal_weights[d] / total, 4)

    @property
    def has_valid_optimal(self) -> bool:
        total = sum(self.optimal_weights.values())
        return abs(total - 1.0) < 0.05 and all(v > 0 for v in self.optimal_weights.values())

    @property
    def is_trusted(self) -> bool:
        return (
            self.has_valid_optimal
            and self.improvement_events >= MIN_IMPROVEMENT_EVENTS
            and self.confidence_gap >= QUALITY_GATE
        )

    @property
    def vote_weight(self) -> float:
        """Higher improvement_events + higher confidence_gap = more vote influence."""
        return float(self.improvement_events) * (1.0 + self.confidence_gap)

    def __repr__(self) -> str:
        return (
            f"RepoSignal({self.repo!r}, gap={self.confidence_gap:.4f}, "
            f"imp={self.improvement_events}, trusted={self.is_trusted})"
        )


# ---------------------------------------------------------------------------
# Harvest
# ---------------------------------------------------------------------------

def harvest(extra_repos: Path) -> List[RepoSignal]:
    """Read all leda_final.yaml files and build RepoSignal objects."""
    signals: List[RepoSignal] = []
    if not extra_repos.exists():
        print(f"[!] Extra repos path not found: {extra_repos}", file=sys.stderr)
        return signals

    for repo_dir in sorted(extra_repos.iterdir()):
        if not repo_dir.is_dir():
            continue
        leda_f = repo_dir / "slop_reports" / "leda_final.yaml"
        if not leda_f.exists():
            continue
        try:
            data = yaml.safe_load(leda_f.read_text(encoding="utf-8", errors="replace"))
            if not isinstance(data, dict):
                continue
            sig = RepoSignal(repo_dir.name, data)
            signals.append(sig)
            trust_marker = "[TRUSTED]" if sig.is_trusted else "[signal]"
            print(
                f"  {trust_marker:10s} {sig.repo:<20s}  "
                f"gap={sig.confidence_gap:.4f}  imp={sig.improvement_events:>4d}  "
                f"fp={sig.fp_candidates:>4d}  "
                f"opt_weights={sig.optimal_weights}"
            )
        except Exception as exc:  # noqa: BLE001
            print(f"  [!] Could not parse {leda_f}: {exc}", file=sys.stderr)

    return signals


# ---------------------------------------------------------------------------
# Synthesize
# ---------------------------------------------------------------------------

def synthesize(signals: List[RepoSignal]) -> Tuple[Dict[str, float], List[str], List[RepoSignal]]:
    """
    Compute globally optimal weights via vote-weighted average.

    Returns (weights, warnings, contributing_signals).
    Falls back to all valid signals (ignoring confidence_gate) if no trusted
    signals exist — with an explicit warning.
    """
    warnings: List[str] = []

    trusted = [s for s in signals if s.is_trusted]
    pool = trusted

    if not pool:
        # Fallback: use all signals that at least have valid optimal weights
        pool = [s for s in signals if s.has_valid_optimal]
        warnings.append(
            f"No trusted signals (gap >= {QUALITY_GATE} + events >= {MIN_IMPROVEMENT_EVENTS}). "
            f"Falling back to {len(pool)} valid-weight signals. "
            "Continue dogfooding to improve confidence."
        )

    if not pool:
        warnings.append("Zero usable signals — keeping existing engine defaults.")
        return {d: 0.0 for d in DIMS}, warnings, []

    # Weighted average
    total_vote = sum(s.vote_weight for s in pool)
    synthesized: Dict[str, float] = {d: 0.0 for d in DIMS}
    for sig in pool:
        w = sig.vote_weight / total_vote
        for d in DIMS:
            synthesized[d] += sig.optimal_weights[d] * w

    # Clamp to [MIN_W, MAX_W] and re-normalize
    synthesized = _clamp_and_normalize(synthesized)

    # Drift warnings
    for d in DIMS:
        v = synthesized[d]
        if v < MIN_W or v > MAX_W:
            warnings.append(f"Dimension '{d}' clamped (raw={v:.3f}) to [{MIN_W}, {MAX_W}].")

    return synthesized, warnings, pool


def _clamp_and_normalize(weights: Dict[str, float]) -> Dict[str, float]:
    clamped = {d: max(MIN_W, min(MAX_W, weights[d])) for d in DIMS}
    total = sum(clamped.values())
    normalized = {d: round(clamped[d] / total, 4) for d in DIMS}
    # Fix float rounding: ensure sum == 1.0 exactly
    residual = round(1.0 - sum(normalized.values()), 4)
    if residual:
        # Add residual to dimension with highest weight (most stable)
        dominant = max(normalized, key=lambda k: normalized[k])
        normalized[dominant] = round(normalized[dominant] + residual, 4)
    return normalized


# ---------------------------------------------------------------------------
# Inject
# ---------------------------------------------------------------------------

def inject_config_py(weights: Dict[str, float], dry_run: bool) -> bool:
    """Rewrite DEFAULT_CONFIG weights + general DOMAIN_PROFILES entry in config.py."""
    if not SRC_CONFIG.exists():
        print(f"[!] config.py not found: {SRC_CONFIG}")
        return False

    text = SRC_CONFIG.read_text(encoding="utf-8")
    original = text

    # --- Patch 1: DEFAULT_CONFIG weights line ---
    # Target:  "weights": {"ldr": 0.40, "inflation": 0.30, "ddc": 0.30},
    pat1 = (
        r'("weights":\s*\{)'
        r'(\s*"ldr":\s*)[\d.]+,'
        r'(\s*"inflation":\s*)[\d.]+,'
        r'(\s*"ddc":\s*)[\d.]+'
        r'(\})'
    )
    repl1 = (
        rf'\g<1>'
        rf'\g<2>{weights["ldr"]}, '
        rf'"inflation": {weights["inflation"]}, '
        rf'"ddc": {weights["ddc"]}'
        rf'\g<5>'
    )
    text, n1 = re.subn(pat1, repl1, text)

    # --- Patch 2: DOMAIN_PROFILES "general" capability_vector ---
    # Target:  "capability_vector": {"ldr": 0.40, "inflation": 0.30, "ddc": 0.20, "purity": 0.10},
    # (first occurrence after DOMAIN_PROFILES assignment)
    pat2 = (
        r'("capability_vector":\s*\{)'
        r'(\s*"ldr":\s*)[\d.]+,'
        r'(\s*"inflation":\s*)[\d.]+,'
        r'(\s*"ddc":\s*)[\d.]+,'
        r'(\s*"purity":\s*)[\d.]+'
        r'(\})'
    )
    repl2 = (
        rf'\g<1>'
        rf'"ldr": {weights["ldr"]}, '
        rf'"inflation": {weights["inflation"]}, '
        rf'"ddc": {weights["ddc"]}, '
        rf'"purity": {weights["purity"]}'
        rf'\g<6>'
    )
    # Only patch the FIRST occurrence (general domain)
    match = re.search(pat2, text)
    if match:
        text = text[:match.start()] + re.sub(pat2, repl2, text[match.start():], count=1)
        n2 = 1
    else:
        n2 = 0

    changed = text != original
    if not dry_run and changed:
        SRC_CONFIG.write_text(text, encoding="utf-8")

    print(f"  config.py      — DEFAULT_CONFIG patch: {'ok' if n1 else 'MISS'}  "
          f"DOMAIN_PROFILES[general] patch: {'ok' if n2 else 'MISS'}  "
          f"{'[DRY-RUN]' if dry_run else '[WRITTEN]'}")
    return changed


def inject_self_calibrator(weights: Dict[str, float], dry_run: bool) -> bool:
    """Rewrite fallback default weights in self_calibrator.py."""
    if not SRC_CALIBRATOR.exists():
        print(f"[!] self_calibrator.py not found: {SRC_CALIBRATOR}")
        return False

    text = SRC_CALIBRATOR.read_text(encoding="utf-8")
    original = text

    # Target:  else {"ldr": 0.40, "inflation": 0.30, "ddc": 0.30}
    pat = (
        r'(else\s*\{)'
        r'(\s*"ldr":\s*)[\d.]+,'
        r'(\s*"inflation":\s*)[\d.]+,'
        r'(\s*"ddc":\s*)[\d.]+'
        r'(\s*\})'
    )
    repl = (
        rf'\g<1>'
        rf'"ldr": {weights["ldr"]}, '
        rf'"inflation": {weights["inflation"]}, '
        rf'"ddc": {weights["ddc"]}'
        rf'\g<5>'
    )
    text, n = re.subn(pat, repl, text)

    changed = text != original
    if not dry_run and changed:
        SRC_CALIBRATOR.write_text(text, encoding="utf-8")

    print(f"  self_calibrator.py — fallback default patch: {'ok' if n else 'MISS'}  "
          f"{'[DRY-RUN]' if dry_run else '[WRITTEN]'}")
    return changed


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

def save_report(
    signals: List[RepoSignal],
    contributors: List[RepoSignal],
    synthesized: Dict[str, float],
    warnings: List[str],
    dry_run: bool,
    out_path: Optional[Path] = None,
) -> None:
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "dry_run": dry_run,
        "quality_gate": QUALITY_GATE,
        "min_improvement_events": MIN_IMPROVEMENT_EVENTS,
        "synthesized_weights": synthesized,
        "warnings": warnings,
        "contributors": [
            {
                "repo": s.repo,
                "confidence_gap": s.confidence_gap,
                "improvement_events": s.improvement_events,
                "fp_candidates": s.fp_candidates,
                "optimal_weights": s.optimal_weights,
                "vote_weight": round(s.vote_weight, 2),
                "trusted": s.is_trusted,
            }
            for s in contributors
        ],
        "all_signals": [
            {
                "repo": s.repo,
                "status": s.status,
                "confidence_gap": s.confidence_gap,
                "improvement_events": s.improvement_events,
                "trusted": s.is_trusted,
            }
            for s in signals
        ],
    }

    out = out_path or (ROOT / "scripts" / "injection_report.json")
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\n  [+] Report written -> {out}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="LEDA Global Weight Injector — Flamehaven Sovereign Asset v1.0"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Compute and display synthesized weights without modifying any source files."
    )
    parser.add_argument(
        "--extra-repos", type=Path, default=DEFAULT_EXTRA_REPOS,
        help=f"Path to Extra Repo root (default: {DEFAULT_EXTRA_REPOS})."
    )
    args = parser.parse_args()

    print("=" * 72)
    print("  LEDA GLOBAL WEIGHT INJECTOR  v1.0  (Flamehaven Sovereign Asset)")
    print("=" * 72)

    # -- HARVEST --
    print(f"\n[STEP 1] Harvesting calibration signals from: {args.extra_repos}\n")
    signals = harvest(args.extra_repos)
    if not signals:
        print("[!] No leda_final.yaml files found. Run leda_turbo.bat first.")
        return 1

    # -- SYNTHESIZE --
    print(f"\n[STEP 2] Synthesizing global optimal weights from {len(signals)} signals...\n")
    synthesized, warnings, contributors = synthesize(signals)

    if all(v == 0.0 for v in synthesized.values()):
        print("[!] Synthesis failed — no usable signals. Aborting.")
        return 1

    print("\n  SYNTHESIZED GLOBAL WEIGHTS:")
    for d in DIMS:
        bar = "#" * int(synthesized[d] * 40)
        print(f"    {d:<12s}  {synthesized[d]:.4f}  |{bar}")
    print(f"\n  Contributing repos: {[s.repo for s in contributors]}")
    print(f"  Total vote weight : {sum(s.vote_weight for s in contributors):.1f}")

    if warnings:
        print("\n  WARNINGS:")
        for w in warnings:
            print(f"    [!] {w}")

    # -- INJECT --
    print(f"\n[STEP 3] Injecting into engine source {'[DRY-RUN]' if args.dry_run else '[LIVE]'}...\n")
    changed_config = inject_config_py(synthesized, args.dry_run)
    changed_cal = inject_self_calibrator(synthesized, args.dry_run)

    # -- REPORT --
    save_report(signals, contributors, synthesized, warnings, args.dry_run)

    print("\n" + "=" * 72)
    if args.dry_run:
        print("  [DRY-RUN COMPLETE] No files modified. Remove --dry-run to apply.")
    else:
        changed = changed_config or changed_cal
        status = "[+] ENGINE UPDATED" if changed else "[=] No change needed (already optimal)"
        print(f"  {status}")
        print("  Weights are now the Global Default for ai-slop-detector.")
        print("  Commit with: git commit -am 'feat(leda): inject dogfooding-calibrated global weights'")
    print("=" * 72)
    return 0


if __name__ == "__main__":
    sys.exit(main())
