"""Command execution helpers for the SLOP detector CLI."""

import argparse
from pathlib import Path


def _run_gate(result) -> None:
    """Display SNP-compatible gate decision."""
    from slop_detector.gate.slop_gate import SlopGate

    gate = SlopGate()
    if hasattr(result, "file_results"):
        avg_ldr = getattr(result, "avg_ldr", 0.0)
        avg_inflation = getattr(result, "avg_inflation", 0.0)
        avg_ddc = getattr(result, "avg_ddc", 1.0)
        pattern_penalty = min(result.deficit_files * 5.0, 50.0)
        decision = gate.evaluate(avg_ldr, avg_ddc, avg_inflation, pattern_penalty, "project")
    else:
        decision = gate.evaluate_from_file_analysis(result)

    print("\n[Gate Decision]")
    print(f"  Status   : {decision.status}")
    print(f"  Allowed  : {decision.allowed}")
    m = decision.metrics_snapshot
    print(f"  sr9={m['sr9']:.4f}  di2={m['di2']:.4f}  jsd={m['jsd']:.4f}  ove={m['ove']:.4f}")
    if decision.halt_reason:
        print(f"  Halt     : {decision.halt_reason}")
    if decision.recommendation:
        print(f"  Recommend: {decision.recommendation}")
    print(f"  AuditHash: {decision.audit_hash[:16]}...")


def _run_autofix(result, dry_run: bool = True) -> None:
    """Run auto-fix engine on analysis results."""
    from slop_detector.autofix.engine import FixEngine

    engine = FixEngine()
    mode = "DRY RUN" if dry_run else "APPLYING"
    print(f"\n[Auto-Fix] {mode}")

    if hasattr(result, "file_results"):
        file_analyses = [
            (fa.file_path, getattr(fa, "pattern_issues", [])) for fa in result.file_results
        ]
    else:
        file_analyses = [(result.file_path, getattr(result, "pattern_issues", []))]

    fix_results = engine.fix_project(file_analyses, dry_run=dry_run)

    if not fix_results:
        print("  [+] No auto-fixable issues found.")
        return

    total_fixed = 0
    for fix_result in fix_results:
        if fix_result.changed:
            print(f"\n  File: {fix_result.file_path}")
            for ch in fix_result.changes:
                print(f"    [L{ch.line}] {ch.pattern_id} (confidence={ch.confidence:.0%})")
                print(f"      - {ch.original.strip()!r}")
                print(f"      + {ch.replacement.strip()!r}")
            total_fixed += fix_result.change_count
        if fix_result.unfixable:
            print(f"  Unfixable (manual): {', '.join(fix_result.unfixable)}")

    action = "Would fix" if dry_run else "Fixed"
    print(f"\n  [+] {action} {total_fixed} issues across {len(fix_results)} files.")
    if dry_run:
        print("  Run without --dry-run to apply changes.")


def _run_js_analysis(path: str) -> None:
    """Analyze JS/TS files in a directory."""
    from slop_detector.languages.js_analyzer import JSAnalyzer

    analyzer = JSAnalyzer()
    target = Path(path)

    if target.is_file() and target.suffix.lower() in (".js", ".jsx", ".ts", ".tsx"):
        results = [analyzer.analyze(str(target))]
    elif target.is_dir():
        results = analyzer.analyze_directory(str(target))
    else:
        print(f"[!] No JS/TS files found at {path}")
        return

    print(f"\n[JS/TS Analysis] {len(results)} files")
    clean = sum(1 for r in results if r.status == "clean")
    suspicious = sum(1 for r in results if r.status == "suspicious")
    critical = sum(1 for r in results if r.status == "critical_deficit")
    print(f"  Clean: {clean}  Suspicious: {suspicious}  Critical: {critical}")

    for r in sorted(results, key=lambda x: x.slop_score, reverse=True):
        if r.status == "clean":
            continue
        print(f"\n  [{r.status.upper()}] {r.file_path}")
        print(f"    Score={r.slop_score:.1f}  LDR={r.ldr_equivalent:.2%}  Issues={len(r.issues)}")
        for issue in r.issues[:5]:
            print(f"    L{issue.line} [{issue.severity}] {issue.message}")


def _run_cross_file(result) -> None:
    """Run cross-file analysis on project results."""
    from slop_detector.analysis.cross_file import CrossFileAnalyzer

    analyzer = CrossFileAnalyzer()
    report = analyzer.analyze(
        result.project_path,
        result.file_results,
    )

    print("\n[Cross-File Analysis]")
    print(f"  Files: {report.total_files}  Risk Score: {report.risk_score:.2f}")

    if report.import_cycles:
        print(f"\n  Import Cycles ({len(report.import_cycles)}):")
        for cycle in report.import_cycles[:5]:
            print(f"    {cycle}")

    if report.duplicates:
        print(f"\n  Duplicate Functions ({len(report.duplicates)}):")
        for dup in report.duplicates[:5]:
            a = Path(dup.file_a).name
            b = Path(dup.file_b).name
            print(f"    {a}:{dup.func_a}() == {b}:{dup.func_b}() (sim={dup.similarity:.0%})")

    if report.hotspots:
        print(f"\n  Slop Hotspots ({len(report.hotspots)}) - heavily imported + sloppy:")
        for h in report.hotspots:
            print(
                f"    {Path(h.file_path).name}  score={h.slop_score:.1f}  imported_by={h.import_count}"
            )

    if not report.import_cycles and not report.duplicates and not report.hotspots:
        print("  [+] No cross-file issues detected.")


def _run_governance(path: str, result) -> None:
    """Emit CR-EP v2.7.2 session artifacts."""
    from slop_detector.governance.session import AnalysisSession

    project_path = Path(path).resolve()
    if not project_path.is_dir():
        project_path = project_path.parent

    session = AnalysisSession(project_path=project_path)

    if hasattr(result, "file_results"):
        planned = [fa.file_path for fa in result.file_results]
        actual = planned
        total_issues = sum(len(getattr(fa, "pattern_issues", [])) for fa in result.file_results)
        halt_count = sum(
            1
            for fa in result.file_results
            if getattr(fa, "status", "") in {"critical_deficit", "suspicious"}
        )
        for fa in result.file_results:
            session.record_file_analyzed(
                file_path=fa.file_path,
                slop_score=getattr(fa, "deficit_score", 0.0),
                status=str(getattr(fa, "status", "unknown")),
                issues_count=len(getattr(fa, "pattern_issues", [])),
            )
    else:
        planned = [result.file_path]
        actual = planned
        total_issues = len(getattr(result, "pattern_issues", []))
        halt_count = 1 if str(getattr(result, "status", "")) == "critical_deficit" else 0
        session.record_file_analyzed(
            file_path=result.file_path,
            slop_score=getattr(result, "deficit_score", 0.0),
            status=str(getattr(result, "status", "unknown")),
            issues_count=total_issues,
        )

    session.record_enforcement("SD-0", "CONFIRMED", f"Analyzing {len(planned)} files")
    cr_ep_dir = session.finalize(planned, actual, total_issues, halt_count)
    print(f"\n[Governance] CR-EP v2.7.2 artifacts written to: {cr_ep_dir}")
    print("  session.json, why_gate.json, scope_declaration.json")
    print("  enforcement_log.jsonl, change_events.jsonl, review_contract.json")


def _detect_project_type(path: Path) -> str:
    """Infer project type from root directory structure."""
    if (path / "package.json").exists():
        return "javascript"
    if (path / "go.mod").exists():
        return "go"
    return "python"  # pyproject.toml / setup.py / .py files — default


def detect_domain(project_path: Path) -> tuple:
    """Scan project imports and return (domain_path, detected_by, confidence).

    Scans all .py files for import statements and matches against DOMAIN_PROFILES
    triggers.  Returns ('general', [], 0.0) when no profile exceeds the threshold.
    """
    import re
    from typing import Dict, List

    from slop_detector.config import DOMAIN_PROFILES

    import_re = re.compile(r"^\s*(?:import\s+([\w]+)|from\s+([\w]+)\s+import)", re.MULTILINE)
    found_imports: set = set()
    try:
        for py_file in project_path.rglob("*.py"):
            try:
                text = py_file.read_text(encoding="utf-8", errors="ignore")
                for m in import_re.finditer(text):
                    mod = (m.group(1) or m.group(2) or "").lower()
                    if mod:
                        found_imports.add(mod)
            except OSError:
                continue
    except OSError as exc:
        import logging as _logging

        _logging.getLogger(__name__).debug("domain detection scan failed: %s", exc)

    scores: Dict[str, List[str]] = {}
    for dp, profile in DOMAIN_PROFILES.items():
        if dp == "general":
            continue
        hits = [t for t in profile.get("triggers", []) if t.lower() in found_imports]
        if hits:
            scores[dp] = hits

    if not scores:
        return "general", [], 0.0

    # Rank by hit count; break ties by specificity (fewer triggers = more specific)
    best = max(
        scores,
        key=lambda k: (len(scores[k]), -len(DOMAIN_PROFILES[k].get("triggers", []) or [1])),
    )
    hits = scores[best]
    n_triggers = max(len(DOMAIN_PROFILES[best].get("triggers", [])), 1)
    confidence = round(min(1.0, len(hits) / max(n_triggers * 0.4, 1)), 2)
    return best, hits, confidence


def _inject_gitignore_entry(gitignore_path: Path, entry: str, comment: str) -> None:
    """Append entry to .gitignore if not already present."""
    if gitignore_path.exists():
        text = gitignore_path.read_text(encoding="utf-8")
        if entry in text:
            return
        with open(gitignore_path, "a", encoding="utf-8") as f:
            f.write(f"\n{comment}\n{entry}\n")
    else:
        with open(gitignore_path, "w", encoding="utf-8") as f:
            f.write(f"{comment}\n{entry}\n")
    print(f"[+] {entry} added to {gitignore_path}")


def _run_init(args: argparse.Namespace) -> int:
    """Bootstrap .slopconfig.yaml and secure it in .gitignore."""
    from slop_detector.config import DOMAIN_PROFILES, generate_slopconfig_template

    config_path = Path(".slopconfig.yaml")
    force = getattr(args, "force_init", False)

    if config_path.exists() and not force:
        print("[!] .slopconfig.yaml already exists. Use --force-init to overwrite.")
        return 1

    project_type = _detect_project_type(Path("."))

    # Domain detection: --domain flag overrides auto-detection
    manual_domain = getattr(args, "domain", None)
    if manual_domain:
        if manual_domain not in DOMAIN_PROFILES:
            valid = ", ".join(DOMAIN_PROFILES.keys())
            print(f"[!] Unknown domain '{manual_domain}'. Valid: {valid}")
            return 1
        domain_path = manual_domain
        detected_by: list = []
        confidence = 1.0
        print(f"[o] Domain: {domain_path} (manually specified)")
    else:
        domain_path, detected_by, confidence = detect_domain(Path("."))
        if domain_path != "general":
            print(
                f"[o] Domain detected: {domain_path} "
                f"(imports: {', '.join(detected_by)}  confidence={confidence:.0%})"
            )
        else:
            print("[o] Domain: general (no specific imports detected)")

    profile = dict(DOMAIN_PROFILES[domain_path])
    profile["detected_by"] = detected_by  # embed for template header comment

    template = generate_slopconfig_template(project_type, domain_profile=profile)
    config_path.write_text(template, encoding="utf-8")
    print(f"[+] .slopconfig.yaml generated (project_type={project_type}, domain={domain_path})")

    _inject_gitignore_entry(
        Path(".gitignore"),
        entry=".slopconfig.yaml",
        comment="# slop-detector: governance config (contains codebase complexity surface — keep private)",
    )

    print()
    print("[>] Next steps:")
    print("    slop-detector --project .")
    print(f"    # domain profile: {profile.get('description', '')}")
    print()
    print("[!] Security: .slopconfig.yaml is in .gitignore (maps acceptable-complexity surface).")
    print("    To share governance config with your team, remove it from .gitignore.")
    return 0


def _compute_project_id() -> str:
    """Return a stable 12-char hex project ID from the resolved cwd (sha256)."""
    import hashlib

    cwd = str(Path.cwd().resolve())
    return hashlib.sha256(cwd.encode()).hexdigest()[:12]


def _check_calibration_hint(args) -> None:
    """At every CALIBRATION_MILESTONE of multi-run files, auto-run calibration and apply if confident.

    v3.5.0 (P1/P2): trigger is now count_files_with_multiple_runs(project_id) — not
    count_total_records(). A first-time scan of N files records N rows but zero
    repeat-file pairs, so total_records % 10 == 0 was a false trigger. Multi-run
    count is the correct proxy for calibration readiness.
    """
    if getattr(args, "no_history", False):
        return
    try:
        import sys as _sys

        from slop_detector.config import Config
        from slop_detector.history import HistoryTracker
        from slop_detector.ml.self_calibrator import CALIBRATION_MILESTONE, SelfCalibrator

        project_id = _compute_project_id()
        tracker = HistoryTracker()
        n = tracker.count_files_with_multiple_runs(project_id=project_id)
        if n < CALIBRATION_MILESTONE or n % CALIBRATION_MILESTONE != 0:
            return

        # Auto-calibrate at milestone
        config = Config(config_path=getattr(args, "config", None))
        current_weights = config.get_weights()
        # P3: use current config weights as domain anchor to constrain grid search
        domain_anchor = {
            k: current_weights.get(k, 0.30) for k in ("ldr", "inflation", "ddc", "purity")
        }
        result = SelfCalibrator().calibrate(
            current_weights=current_weights,
            project_id=project_id,
            domain_anchor=domain_anchor,
        )
        config_path = getattr(args, "config", None) or ".slopconfig.yaml"

        if result.status == "ok" and Path(config_path).exists():
            written = SelfCalibrator.apply_to_config(
                result.optimal_weights, config_path=config_path
            )
            print(
                f"\n[*] Auto-calibration ({n} multi-run files): weights updated -> {written}",
                file=_sys.stderr,
            )
            for k in ("ldr", "inflation", "ddc", "purity"):
                old_v = current_weights.get(k, 0.0)
                new_v = result.optimal_weights.get(k, 0.0)
                if abs(old_v - new_v) > 0.001:
                    print(f"    {k}: {old_v:.2f} -> {new_v:.2f}", file=_sys.stderr)
        elif result.status == "no_change":
            print(
                f"\n[*] Calibration milestone ({n} multi-run files): weights already optimal.",
                file=_sys.stderr,
            )
        else:
            print(
                f"\n[*] Calibration milestone ({n} multi-run files): {result.message} "
                f"Run --self-calibrate for details.",
                file=_sys.stderr,
            )
    except Exception as exc:  # noqa: BLE001 — hint is informational; never block main flow
        import logging as _logging

        _logging.getLogger(__name__).debug("calibration hint skipped: %s", exc)


def _get_git_context():
    """Capture current git commit (short SHA) and branch. Returns (None, None) if not in a repo."""
    import subprocess

    try:
        commit = (
            subprocess.run(
                ["git", "rev-parse", "--short", "HEAD"],
                capture_output=True,
                text=True,
                timeout=3,
            ).stdout.strip()
            or None
        )
        branch = (
            subprocess.run(
                ["git", "branch", "--show-current"],
                capture_output=True,
                text=True,
                timeout=3,
            ).stdout.strip()
            or None
        )
        return commit, branch
    except Exception:
        return None, None


def _record_history(result) -> None:
    """Auto-record analysis result(s) to history DB with git context and project_id."""
    try:
        from slop_detector.history import HistoryTracker

        git_commit, git_branch = _get_git_context()
        project_id = _compute_project_id()
        tracker = HistoryTracker()
        if hasattr(result, "file_results"):
            for fa in result.file_results:
                tracker.record(
                    fa, git_commit=git_commit, git_branch=git_branch, project_id=project_id
                )
        else:
            tracker.record(
                result, git_commit=git_commit, git_branch=git_branch, project_id=project_id
            )
    except Exception as exc:  # noqa: BLE001 — history is best-effort; never block main flow
        import logging as _logging

        _logging.getLogger(__name__).debug("history record skipped: %s", exc)


def _show_file_history(file_path: str) -> None:
    """Print trend history for a single file."""
    from slop_detector.history import HistoryTracker

    tracker = HistoryTracker()
    resolved = str(Path(file_path).resolve())
    history = tracker.get_file_history(resolved, limit=20)
    file_path = resolved

    if not history:
        print(f"No history found for: {file_path}")
        print(f"  DB: {tracker.db_path}")
        return

    print(f"History: {file_path}")
    print(f"  DB: {tracker.db_path}")
    print("-" * 70)
    print(f"  {'Timestamp':<24} {'Deficit':>7} {'LDR':>6} {'Patterns':>8}  Grade")
    print("-" * 70)
    for h in history:
        ts = h["timestamp"][:19]
        print(
            f"  {ts:<24} {h['deficit_score']:>7.1f} {h['ldr_score']:>6.3f}"
            f" {h['pattern_count']:>8}  {h['grade']}"
        )

    if len(history) >= 2:
        first = history[-1]["deficit_score"]
        last = history[0]["deficit_score"]
        delta = last - first
        direction = "improved" if delta < 0 else "degraded" if delta > 0 else "stable"
        print("-" * 70)
        print(f"  Trend ({len(history)} runs): {direction}  delta={delta:+.1f}")


def _show_trends() -> None:
    """Print project-wide daily trend table."""
    from slop_detector.history import HistoryTracker

    tracker = HistoryTracker()
    trends = tracker.get_project_trends(days=7)

    if not trends["data_points"]:
        print("No history found.")
        print(f"  DB: {tracker.db_path}")
        return

    print("Project Trends (last 7 days)")
    print(f"  DB: {tracker.db_path}")
    print("-" * 65)
    print(f"  {'Date':<12} {'Avg Deficit':>11} {'Avg LDR':>8} {'Patterns':>9} {'Files':>6}")
    print("-" * 65)
    for d in trends["daily_trends"]:
        print(
            f"  {d['date']:<12} {d['avg_deficit']:>11.1f} {d['avg_ldr']:>8.3f}"
            f" {d['total_patterns']:>9} {d['files_analyzed']:>6}"
        )


def _export_history(output_path: str) -> None:
    """Export history to JSONL."""
    from slop_detector.history import HistoryTracker

    tracker = HistoryTracker()
    count = tracker.export_jsonl(output_path)
    print(f"[+] Exported {count} records to {output_path}")


def _run_self_calibration(args: argparse.Namespace) -> int:
    """Run self-calibration and optionally apply results to .slopconfig.yaml."""
    from slop_detector.config import Config
    from slop_detector.ml.self_calibrator import SelfCalibrator

    try:
        from rich import box
        from rich.console import Console
        from rich.table import Table

        console = Console()
        _rich = True
    except ImportError:
        console = None  # type: ignore[assignment]
        _rich = False

    config = Config(config_path=getattr(args, "config", None))
    current_weights = config.get_weights()
    min_events = getattr(args, "min_history", 5)

    calibrator = SelfCalibrator()
    result = calibrator.calibrate(current_weights=current_weights, min_events=min_events)

    # --- Print summary ---
    if _rich and console:
        from rich.panel import Panel
        from rich.text import Text

        status_color = {"ok": "green", "no_change": "yellow", "insufficient_data": "red"}.get(
            result.status, "white"
        )
        header = Text(f"Self-Calibration — {result.status.upper()}", style=f"bold {status_color}")
        console.print(Panel(header, box=box.ROUNDED))

        t = Table(box=box.ROUNDED, show_header=True, header_style="bold cyan")
        t.add_column("Metric", style="cyan")
        t.add_column("Value", justify="right")
        t.add_row("Unique files in history", str(result.unique_files))
        t.add_row("Improvement events (true positives)", str(result.improvement_events))
        t.add_row("FP candidates (flagged, never fixed)", str(result.fp_candidates))
        t.add_row("Confidence gap", f"{result.confidence_gap:.4f}")
        console.print(t)

        wt = Table(box=box.ROUNDED, show_header=True, header_style="bold cyan")
        wt.add_column("Dimension", style="cyan")
        wt.add_column("Current", justify="right")
        wt.add_column("Optimal", justify="right")
        wt.add_column("Delta", justify="right")
        for dim in ("ldr", "inflation", "ddc", "purity"):
            cur = current_weights.get(dim, 0.0)
            opt = result.optimal_weights.get(dim, cur)
            delta = opt - cur
            delta_str = f"{delta:+.2f}" if abs(delta) > 0.001 else "—"
            color = "green" if delta < -0.001 else ("red" if delta > 0.001 else "white")
            wt.add_row(dim, f"{cur:.2f}", f"{opt:.2f}", f"[{color}]{delta_str}[/{color}]")
        console.print(wt)

        if result.status == "ok":
            err_before = result.fn_rate_before + result.fp_rate_before
            err_after = result.fn_rate_after + result.fp_rate_after
            console.print(
                f"\nCombined error: [yellow]{err_before:.4f}[/yellow] -> [green]{err_after:.4f}[/green]"
                f"  (FN {result.fn_rate_before:.4f}->{result.fn_rate_after:.4f},"
                f"  FP {result.fp_rate_before:.4f}->{result.fp_rate_after:.4f})"
            )

        # Per-rule FP rates (v3.4.0): show rules with notable FP behaviour
        high_fp = {
            rid: rate
            for rid, rate in sorted(result.per_rule_fp_rates.items(), key=lambda x: -x[1])
            if rate >= 0.5
        }
        if high_fp:
            rt = Table(
                box=box.ROUNDED,
                show_header=True,
                header_style="bold cyan",
                title="Per-Rule FP Rates (>= 50%)",
            )
            rt.add_column("Rule ID", style="cyan")
            rt.add_column("FP Rate", justify="right")
            rt.add_column("Signal", justify="right")
            for rid, rate in high_fp.items():
                signal = "[red]HIGH FP[/red]" if rate >= 0.7 else "[yellow]MOD FP[/yellow]"
                rt.add_row(rid, f"{rate:.0%}", signal)
            console.print(rt)
            console.print(
                "[dim]Rules with HIGH FP (>=70%) are candidates for suppression"
                " via .slopconfig.yaml exclude_rules[/dim]"
            )

        if result.warnings:
            for w in result.warnings:
                console.print(f"[yellow][!] {w}[/yellow]")
        console.print(f"\n[dim]{result.message}[/dim]")
    else:
        print(f"[Self-Calibration] status={result.status}")
        print(f"  unique_files={result.unique_files}")
        print(f"  improvement_events={result.improvement_events}")
        print(f"  fp_candidates={result.fp_candidates}")
        print(f"  confidence_gap={result.confidence_gap:.4f}")
        print(f"  current_weights={current_weights}")
        print(f"  optimal_weights={result.optimal_weights}")
        if result.per_rule_fp_rates:
            high_fp_plain = {
                rid: rate
                for rid, rate in sorted(result.per_rule_fp_rates.items(), key=lambda x: -x[1])
                if rate >= 0.5
            }
            if high_fp_plain:
                print("  per_rule_fp_rates (>=50%):")
                for rid, rate in high_fp_plain.items():
                    print(f"    {rid}: {rate:.0%}")
        for w in result.warnings:
            print(f"  [!] {w}")
        print(f"  {result.message}")

    # --- Apply if requested ---
    apply_path = getattr(args, "apply_calibration", None)
    if apply_path and result.status == "ok":
        written = SelfCalibrator.apply_to_config(result.optimal_weights, config_path=apply_path)
        msg = f"[+] Calibrated weights written to {written}"
        if _rich and console:
            console.print(f"\n[green]{msg}[/green]")
        else:
            print(msg)
    elif apply_path and result.status != "ok":
        msg = "[-] --apply-calibration skipped: calibration did not produce a confident result."
        if _rich and console:
            console.print(f"\n[yellow]{msg}[/yellow]")
        else:
            print(msg)

    return 0 if result.status in ("ok", "no_change") else 1
