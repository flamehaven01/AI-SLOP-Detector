"""Command execution helpers and compatibility re-exports for the CLI."""

import sys
from pathlib import Path

from slop_detector.cli_history import (
    _check_calibration_hint,  # noqa: F401
    _export_history,  # noqa: F401
    _get_git_context,  # noqa: F401
    _record_history,  # noqa: F401
    _run_self_calibration,  # noqa: F401
    _show_file_history,  # noqa: F401
    _show_trends,  # noqa: F401
)
from slop_detector.cli_init import (
    _run_init,  # noqa: F401
    collect_init_signals,  # noqa: F401
    detect_domain,  # noqa: F401
    synthesize_init_suggestions,  # noqa: F401
)


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
    ml_scoring = getattr(result, "ml_scoring", {})
    if ml_scoring and ml_scoring.get("status") != "available":
        print(f"  Capability: PARTIAL (ML scoring {ml_scoring.get('status')})")
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
        connections=True,
    )

    print("\n[Cross-File Analysis]")
    print(f"  Files: {report.total_files}")
    evidence = report.structure_evidence
    _print_import_resolution(evidence["coverage"])

    if report.import_cycles:
        print(f"\n  Import Cycles ({len(report.import_cycles)}):")
        for cycle in report.import_cycles[:5]:
            print(f"    {cycle}")

    _print_graph_structure(evidence)

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
        _print_no_issue_verdict(evidence["coverage"])

    _print_connections(evidence["connections"])


_CONNECTION_SHOWN = 5


def _print_connections(block) -> None:
    """Connection evidence summary; candidates are for review, not findings."""
    summary = block["summary"]
    print(
        f"\n  Connections ({summary['candidates']} top-level functions/classes): "
        f"{summary['connected']} connected, {summary['externally_exposed']} exposed, "
        f"{summary['dynamic_unknown']} dynamic, {summary['unmeasured']} unmeasured, "
        f"{summary['disconnected_candidate']} disconnected candidates"
    )
    candidates = [r for r in block["symbols"] if r["state"] == "disconnected_candidate"]
    if not candidates:
        return
    print("  Disconnected candidates (no connection evidence found; review before acting):")
    for row in candidates[:_CONNECTION_SHOWN]:
        tested = " (referenced by tests)" if row["test_referenced"] else ""
        print(f"    {Path(row['file']).name}:{row['line']} {row['name']}{tested}")
    if len(candidates) > _CONNECTION_SHOWN:
        print(f"    ... and {len(candidates) - _CONNECTION_SHOWN} more")
    if not summary["test_files_seen"]:
        print("  Test files were not in the scan, so test references are not known.")


_PHASE_WORDS = {
    "import_time": "import-time",
    "deferred_runtime": "only when a function runs",
    "type_only": "type-checking only",
}


_INNER_WORDS = {"import_time": "import-time", "deferred_runtime": "function-level"}


def _print_graph_structure(evidence) -> None:
    """Circular groups and the most imported file, from structure_evidence."""
    groups = evidence.get("circular_groups", [])
    if groups:
        print(f"\n  Circular Groups ({len(groups)}):")
        for group in groups[:5]:
            names = ", ".join(Path(f).name for f in group["files"][:4])
            more = f" +{group['size'] - 4} more" if group["size"] > 4 else ""
            phase = _PHASE_WORDS.get(group["execution_phase"], group["execution_phase"])
            print(f"    {group['size']} files, {phase}: {names}{more}")
            for inner in group.get("inner_cycles", [])[:2]:
                kind = _INNER_WORDS.get(inner["execution_phase"], inner["execution_phase"])
                inner_names = ", ".join(Path(f).name for f in inner["files"][:4])
                print(f"      inner {kind} cycle: {inner_names}")
    busiest = (evidence.get("dependency_hubs") or [None])[0]
    if busiest:
        print(f"  Most imported: {Path(busiest['file']).name} ({busiest['count']} files)")


def _print_import_resolution(coverage) -> None:
    print(
        f"  Imports: {coverage.get('resolved', 0)} resolved, "
        f"{coverage.get('conditional_internal', 0)} conditional, "
        f"{coverage.get('ambiguous', 0)} ambiguous, "
        f"{coverage.get('unresolved_internal', 0)} unresolved internal"
    )


def _print_no_issue_verdict(coverage) -> None:
    """A clean result covers resolved imports only; say what was not checked."""
    from slop_detector.analysis.import_graph import unchecked_imports

    unchecked = unchecked_imports(coverage)
    if not unchecked:
        print("  [+] No cross-file issues detected.")
        return
    print(
        f"  [!] No cross-file issues among resolved imports; {unchecked} internal imports "
        "(conditional, ambiguous or unresolved) were not checked."
    )
    if coverage.get("conditional_internal", 0):
        print(
            "      To include conditional ones, declare the module roots in pyproject.toml: "
            "[tool.setuptools.packages.find] where = [...]"
        )


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


def _resolve_governance_record_path(target: str) -> Path:
    path = Path(target)
    if path.is_dir():
        candidate = path / ".cr-ep" / "governance_record.json"
        if candidate.exists():
            return candidate
        candidate = path / "governance_record.json"
        if candidate.exists():
            return candidate
    if path.is_file():
        return path
    candidate = path / ".cr-ep" / "governance_record.json"
    if candidate.exists():
        return candidate
    return path


def _run_verify_governance(target: str) -> int:
    """Verify governance artifact integrity and policy constraints."""
    from slop_detector.governance.verification import (
        GovernanceVerificationError,
        verify_governance_record,
    )

    record_path = _resolve_governance_record_path(target)
    try:
        record, computed_hash = verify_governance_record(record_path)
    except GovernanceVerificationError as exc:
        print(f"[!] Governance verification failed: {exc}", file=sys.stderr)
        return 1

    print("[Governance Verification]")
    print(f"  Record     : {record_path}")
    print(f"  Hash       : {computed_hash[:16]}...")
    print(f"  Session    : {record.get('session_id', 'unknown')}")
    print("  Integrity  : PASS")
    print("  Policy     : PASS")
    return 0
