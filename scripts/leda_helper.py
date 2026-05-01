"""
LEDA Turbo Helper — auto-selects top N files, runs fix cycles, compares LEDA state.

Usage:
    python leda_helper.py select    scan_1.json [N]
    python leda_helper.py fixloop   selected_files.txt PYTHON_PATH [CFG_PATH]
    python leda_helper.py compare   leda_1.yaml leda_final.yaml
    python leda_helper.py delta     scan_1.json scan_final.json
    python leda_helper.py gapcheck  leda_final.yaml
"""
from __future__ import annotations
import json
import subprocess
import sys
import yaml
from pathlib import Path

UNFIXABLE = {"god_function", "function_clone_cluster", "nested_complexity"}
AUTOFIX   = {"bare_except", "pass_placeholder", "ellipsis_placeholder",
             "mutable_default_arg", "js_push", "js_length", "js_to_lower",
             "js_to_upper", "csharp_length", "csharp_to_lower"}


def _load_scan(scan_json: str) -> dict:
    """Load scan JSON, skipping [INFO] prefix lines. Handles multiple JSON objects."""
    txt   = Path(scan_json).read_text(encoding="utf-8", errors="ignore")
    lines = txt.split("\n")
    idx   = next((i for i, l in enumerate(lines) if l.strip().startswith("{")), None)
    if idx is None:
        return {}
    json_str = "\n".join(lines[idx:])
    try:
        return json.loads(json_str)
    except json.JSONDecodeError:
        # CLI may output multiple JSON objects -- parse only the first one
        try:
            obj, _ = json.JSONDecoder().raw_decode(json_str)
            return obj
        except json.JSONDecodeError:
            return {}


def cmd_select(scan_json: str, n: int = 3) -> None:
    """Print top N files by fixable_ratio (fixable patterns / total patterns)."""
    data    = _load_scan(scan_json)
    results = data.get("file_results", [])

    # Classify all files
    classified = []
    for r in results:
        score = r.get("deficit_score", 0)
        if score == 0:
            continue
        path  = r.get("file_path", "")
        pats  = [i.get("pattern_id", "") for i in r.get("pattern_issues", [])]

        fixable   = [p for p in pats if p in AUTOFIX]
        unfixable = [p for p in pats if p in UNFIXABLE]
        manual    = [p for p in pats if p not in AUTOFIX and p not in UNFIXABLE]

        total = len(pats)
        fixable_ratio = len(fixable) / max(total, 1)
        # Structural ceiling: unfixable patterns dominate → score won't drop even after fix
        structural_ceiling = len(unfixable) > 2 or (len(unfixable) + len(manual)) > len(fixable) * 3

        classified.append({
            "path": path,
            "score": score,
            "fixable": fixable,
            "unfixable": unfixable,
            "manual": manual,
            "fixable_ratio": fixable_ratio,
            "structural_ceiling": structural_ceiling,
        })

    # Sort order:
    #   1. Has auto-fixable patterns (True first)
    #   2. No structural ceiling (False first = no ceiling)
    #   3. Fixable ratio (desc)
    #   4. Score (desc)
    classified.sort(key=lambda x: (
        0 if x["fixable"] else 1,
        1 if x["structural_ceiling"] else 0,
        -x["fixable_ratio"],
        -x["score"],
    ))

    print("=== TOP FILES BY FIXABLE RATIO ===")
    selected = []
    for c in classified:
        fixable   = c["fixable"]
        unfixable = c["unfixable"]
        manual    = c["manual"]
        score     = c["score"]
        path      = c["path"]
        ceiling   = c["structural_ceiling"]
        ratio     = c["fixable_ratio"]

        if fixable:
            tag = "[AUTO-FIXABLE]"
            if ceiling:
                tag = "[AUTO-FIX/CEIL]"  # has fixes but ceiling exists
        elif manual:
            tag = "[MANUAL-FIX]"
        elif unfixable:
            tag = "[STRUCTURAL-SKIP]"
        else:
            tag = "[CLEAN]"

        ceiling_flag = " !CEILING" if ceiling else ""
        print(f"  {tag:18s}  ratio={ratio:.0%}  score={score:5.1f}  {Path(path).name}{ceiling_flag}")
        if fixable:   print(f"    auto-fix: {', '.join(fixable)}")
        if manual:    print(f"    manual:   {', '.join(manual)}")
        if unfixable: print(f"    skip:     {', '.join(unfixable)}")

        if tag not in ("[STRUCTURAL-SKIP]", "[MANUAL-FIX]"):
            selected.append(path)
        elif tag == "[MANUAL-FIX]" and not selected:  # fallback if nothing auto-fixable
            selected.append(path)
        if len(selected) >= n:
            break

    print()
    print("=== SELECTED FOR FIX CYCLE ===")
    for p in selected:
        print(p)

    out = Path(scan_json).parent / "selected_files.txt"
    out.write_text("\n".join(selected), encoding="utf-8")
    print(f"\n[Saved to {out}]")


def cmd_fixloop(selected_txt: str, python_path: str, cfg_path: str = "") -> None:
    """
    Run the full fix cycle for each selected file.
    All subprocess calls happen here -- no BAT loop needed.
    """
    sel_file = Path(selected_txt)
    if not sel_file.exists() or sel_file.stat().st_size == 0:
        print("[!] No selected files. Skipping fix loop.")
        return

    files = [l.strip() for l in sel_file.read_text(encoding="utf-8").splitlines() if l.strip()]
    report_dir = sel_file.parent

    cfg_args = ["--config", cfg_path] if cfg_path and Path(cfg_path).exists() else []
    base_cmd  = [python_path, "-m", "slop_detector.cli"]

    for fpath in files:
        fname = Path(fpath).name
        print()
        print("=" * 60)
        print(f"  [FILE] {fname}")
        print("=" * 60)

        before_json = str(report_dir / f"{fname}_before.json")
        after_json  = str(report_dir / f"{fname}_after.json")
        preview_txt = str(report_dir / f"{fname}_fix_preview.txt")
        fix_txt     = str(report_dir / f"{fname}_fix.txt")

        # --- Pre-fix scan ---
        print(f"[SCAN-BEFORE] {fname}")
        r = subprocess.run(base_cmd + [fpath, "--json"] + cfg_args,
                           capture_output=True, text=True, encoding="utf-8", errors="ignore")
        Path(before_json).write_text(r.stdout + r.stderr, encoding="utf-8")

        # --- Dry-run preview ---
        print(f"[DRY-RUN]     {fname}")
        r = subprocess.run(base_cmd + [fpath, "--fix", "--dry-run"] + cfg_args,
                           capture_output=True, text=True, encoding="utf-8", errors="ignore")
        preview = r.stdout + r.stderr
        Path(preview_txt).write_text(preview, encoding="utf-8")
        print(preview[:1200] if len(preview) > 1200 else preview)

        # --- User decision ---
        zero_fixable = "[+] Would fix 0 issues" in preview
        if zero_fixable:
            print("[AUTO-SKIP] Dry-run confirms 0 auto-fixable issues.")
            print(f"  [>] {fname} recorded as FP candidate (structural issues).")
            continue

        has_autofix = any(p in preview.lower() for p in ["fixed", "change", "replace", "would fix"])
        
        auto_mode = "--auto" in sys.argv
        if auto_mode:
            if not has_autofix:
                print("[AUTO-MODE] Skipping: no clear auto-fixable patterns.")
                choice = "S"
            else:
                print("[AUTO-MODE] Proceeding with fix.")
                choice = ""
        else:
            if not has_autofix:
                print("[INFO] No clearly auto-fixable patterns detected.")
                choice = input("  [S=skip (recommended) | Enter=attempt anyway]: ").strip().upper()
            else:
                choice = input("  [Enter=apply fix | S=skip]: ").strip().upper()

        if choice == "S":
            print(f"[SKIP] {fname} recorded as FP candidate.")
            continue

        # --- Apply fix ---
        print(f"[AUTO-FIX]    Applying to {fname}...")
        r = subprocess.run(base_cmd + [fpath, "--fix"] + cfg_args,
                           capture_output=True, text=True, encoding="utf-8", errors="ignore")
        Path(fix_txt).write_text(r.stdout + r.stderr, encoding="utf-8")
        print(r.stdout[:800] if r.stdout else "(no output)")

        # --- Post-fix scan ---
        print(f"[SCAN-AFTER]  {fname}")
        r = subprocess.run(base_cmd + [fpath, "--json"] + cfg_args,
                           capture_output=True, text=True, encoding="utf-8", errors="ignore")
        Path(after_json).write_text(r.stdout + r.stderr, encoding="utf-8")

        # --- Delta ---
        print()
        print(f"[DELTA] {fname}:")
        try:
            cmd_delta(before_json, after_json)
        except Exception as e:
            print(f"  [!] Delta failed: {e}")
            print(f"  [>] Continuing to next file...")

    print()
    print("[fixloop] Done.")


def cmd_compare(leda_before: str, leda_after: str) -> None:
    """Compare two LEDA YAML snapshots."""
    def load(p):
        return yaml.safe_load(Path(p).read_text(encoding="utf-8", errors="ignore"))

    before = load(leda_before)
    after  = load(leda_after)
    cal_b  = before.get("calibration", {})
    cal_a  = after.get("calibration",  {})

    gap_b = cal_b.get("confidence_gap",    0.0)
    gap_a = cal_a.get("confidence_gap",    0.0)
    imp_b = cal_b.get("improvement_events", 0)
    imp_a = cal_a.get("improvement_events", 0)
    fp_b  = cal_b.get("fp_candidates",     0)
    fp_a  = cal_a.get("fp_candidates",     0)

    W = 56
    print("=" * W)
    print("  LEDA STATE DELTA")
    print("=" * W)
    print(f"  {'Metric':<28}  {'Before':>8}  {'After':>8}  {'Delta':>8}")
    print(f"  {'-'*28}  {'-'*8}  {'-'*8}  {'-'*8}")
    print(f"  {'confidence_gap':<28}  {gap_b:>8.4f}  {gap_a:>8.4f}  {gap_a-gap_b:>+8.4f}")
    print(f"  {'improvement_events':<28}  {imp_b:>8}  {imp_a:>8}  {imp_a-imp_b:>+8}")
    print(f"  {'fp_candidates':<28}  {fp_b:>8}  {fp_a:>8}  {fp_a-fp_b:>+8}")
    print()

    opt_b = cal_b.get("optimal_weights", {})
    opt_a = cal_a.get("optimal_weights", {})
    cur   = cal_a.get("current_weights",  {})
    if opt_b and opt_a:
        print("  OPTIMAL WEIGHT DRIFT:")
        for dim in ("ldr", "inflation", "ddc", "purity"):
            vb = opt_b.get(dim, 0.0)
            va = opt_a.get(dim, 0.0)
            vc = cur.get(dim, 0.0)
            print(f"    {dim:<12}  opt_before={vb:.2f}  opt_after={va:.2f}"
                  f"  current={vc:.2f}  drift={va-vb:+.2f}")
    print()

    threshold = 0.10
    if gap_a >= threshold:
        print(f"  [SUCCESS] confidence_gap {gap_a:.4f} >= {threshold}")
        print("  --> Run --apply-calibration")
    elif gap_a > gap_b:
        pct = ((threshold - gap_a) / threshold) * 100
        print(f"  [PROGRESS] gap {gap_b:.4f} -> {gap_a:.4f}  ({pct:.0f}% more needed)")
    else:
        print(f"  [NO SIGNAL] gap did not improve ({gap_a:.4f})")
    print("=" * W)


def cmd_delta(scan_before: str, scan_after: str) -> None:
    """Show score delta between two project scans."""
    before = _load_scan(scan_before)
    after  = _load_scan(scan_after)
    if not before or not after:
        print("  [!] Could not load scan files for delta.")
        return

    b_avg = before.get("avg_deficit_score", 0)
    a_avg = after.get("avg_deficit_score",  0)
    W = 56
    print("=" * W)
    print("  SCORE DELTA")
    print("=" * W)
    print(f"  avg_deficit:  {b_avg:.2f} -> {a_avg:.2f}  ({a_avg-b_avg:>+.2f})")
    print(f"  status:       {before.get('overall_status')} -> {after.get('overall_status')}")
    print()

    b_files = {r["file_path"]: r for r in before.get("file_results", [])}
    a_files = {r["file_path"]: r for r in after.get("file_results",  [])}
    for path, br in b_files.items():
        ar = a_files.get(path)
        if not ar:
            continue
        bs  = br.get("deficit_score", 0)
        as_ = ar.get("deficit_score", 0)
        if abs(as_ - bs) > 0.01:
            arrow = "improved" if as_ < bs else "REGRESSED"
            print(f"  {Path(path).name:<30}  {bs:6.1f} -> {as_:6.1f}  [{arrow}]")
    print("=" * W)


def cmd_gapcheck(leda_yaml: str) -> None:
    """Print OK or LOW:<gap> for calibration gate decision."""
    d   = yaml.safe_load(Path(leda_yaml).read_text(encoding="utf-8", errors="ignore"))
    gap = d.get("calibration", {}).get("confidence_gap", 0)
    if gap >= 0.10:
        print("OK")
    else:
        print(f"LOW {round(gap, 4)}")


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)

    cmd = sys.argv[1]
    if cmd == "select":
        cmd_select(sys.argv[2], int(sys.argv[3]) if len(sys.argv) > 3 else 3)
    elif cmd == "fixloop":
        cfg = sys.argv[4] if len(sys.argv) > 4 else ""
        cmd_fixloop(sys.argv[2], sys.argv[3], cfg)
    elif cmd == "compare":
        cmd_compare(sys.argv[2], sys.argv[3])
    elif cmd == "delta":
        cmd_delta(sys.argv[2], sys.argv[3])
    elif cmd == "gapcheck":
        cmd_gapcheck(sys.argv[2])
    else:
        print(f"Unknown command: {cmd}")
        sys.exit(1)
