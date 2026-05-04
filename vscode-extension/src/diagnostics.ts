import * as vscode from 'vscode';
import { diagnosticCollection } from './state';

const FILE_TOP  = new vscode.Range(0, 0, 0, 0);
const FULL_LINE = new vscode.Range(0, 0, 0, 1000);

function lineRange(line: number | undefined): vscode.Range {
    const l = Math.max(0, (line || 1) - 1);
    return new vscode.Range(l, 0, l, 1000);
}

function makeDiag(
    range: vscode.Range,
    message: string,
    severity: vscode.DiagnosticSeverity,
    source: string,
    code?: string,
): vscode.Diagnostic {
    const d = new vscode.Diagnostic(range, message, severity);
    d.source = source;
    if (code) { d.code = code; }
    return d;
}

export function updateDiagnostics(uri: vscode.Uri, result: any): void {
    const diagnostics: vscode.Diagnostic[] = [];
    const config = vscode.workspace.getConfiguration('slopDetector');
    const failThreshold = config.get('failThreshold', 50.0) as number;
    const warnThreshold = config.get('warnThreshold', 30.0) as number;
    const deficitScore  = result.deficit_score || 0;

    let overallSev = vscode.DiagnosticSeverity.Information;
    if (deficitScore >= failThreshold)      { overallSev = vscode.DiagnosticSeverity.Error; }
    else if (deficitScore >= warnThreshold) { overallSev = vscode.DiagnosticSeverity.Warning; }

    const cloneIssues = (result.pattern_issues || []).filter(
        (i: any) => i.pattern_id === 'function_clone_cluster'
    );
    const clonePart  = cloneIssues.length > 0
        ? `, Clone: ${cloneIssues[0].severity?.toUpperCase() ?? 'DETECTED'}` : '';
    const nCritical  = (result.pattern_issues ?? []).filter(
        (i: any) => (i.severity ?? '').toLowerCase() === 'critical'
    ).length;
    const purity     = Math.exp(-0.5 * nCritical);
    const mlPart     = result.ml_score
        ? `, ML: ${(result.ml_score.slop_probability * 100).toFixed(0)}% [${result.ml_score.label}]`
        : '';

    // Summary diagnostic at top of file
    diagnostics.push(makeDiag(
        FILE_TOP,
        `Code Quality Score: ${deficitScore.toFixed(1)}/100 — ` +
        `${(result.status ?? 'unknown').toUpperCase()}${mlPart}${clonePart}\n` +
        `LDR: ${(result.ldr?.ldr_score ?? 0).toFixed(3)}  ` +
        `Inflation: ${(result.inflation?.inflation_score ?? 0).toFixed(3)}  ` +
        `DDC: ${(result.ddc?.usage_ratio ?? 0).toFixed(3)}  ` +
        `Purity: ${purity.toFixed(3)} (${nCritical} critical)`,
        overallSev, 'SLOP Detector',
    ));

    for (const jargon of result.inflation?.jargon_details ?? []) {
        diagnostics.push(makeDiag(
            lineRange(jargon.line),
            `Unjustified jargon: "${jargon.word}" (${jargon.category})`,
            vscode.DiagnosticSeverity.Warning, 'SLOP Detector - Inflation', 'jargon',
        ));
    }

    for (const detail of result.docstring_inflation?.details ?? []) {
        const ratio = detail.ratio != null ? detail.ratio.toFixed(1) : '?';
        diagnostics.push(makeDiag(
            lineRange(detail.line),
            `Docstring inflation: ${detail.name} ` +
            `(${detail.docstring_lines} doc / ${detail.implementation_lines} impl = ${ratio}x)`,
            (detail.severity || '').toLowerCase() === 'critical'
                ? vscode.DiagnosticSeverity.Error : vscode.DiagnosticSeverity.Warning,
            'SLOP Detector - Docstring', 'docstring-inflation',
        ));
    }

    for (const ev of result.context_jargon?.evidence_details ?? []) {
        if (ev.is_justified === false) {
            const missing = Array.isArray(ev.missing_evidence)
                ? ev.missing_evidence.join(', ') : String(ev.missing_evidence || 'unknown');
            diagnostics.push(makeDiag(
                lineRange(ev.line),
                `"${ev.jargon}" claim lacks evidence: ${missing}`,
                vscode.DiagnosticSeverity.Warning, 'SLOP Detector - Evidence', 'unjustified-claim',
            ));
        }
    }

    if (result.ddc?.unused?.length > 0) {
        diagnostics.push(makeDiag(
            FULL_LINE, `Unused imports: ${result.ddc.unused.join(', ')}`,
            vscode.DiagnosticSeverity.Information, 'SLOP Detector - DDC', 'unused-import',
        ));
    }

    for (const dep of result.hallucination_deps?.hallucinated_deps ?? []) {
        diagnostics.push(makeDiag(
            FULL_LINE,
            `Hallucinated dependency: "${dep.name || dep}" — imported but serves no verified purpose`,
            vscode.DiagnosticSeverity.Information, 'SLOP Detector - Hallucination', 'hallucinated-dep',
        ));
    }

    for (const issue of result.pattern_issues ?? []) {
        const sev = issue.severity?.toLowerCase() || 'medium';
        let diagSev = vscode.DiagnosticSeverity.Information;
        if (sev === 'critical')    { diagSev = vscode.DiagnosticSeverity.Error; }
        else if (sev === 'high')   { diagSev = vscode.DiagnosticSeverity.Warning; }
        const msg = issue.suggestion
            ? `${issue.message || 'Pattern issue'}\nSuggestion: ${issue.suggestion}`
            : (issue.message || 'Pattern issue detected');
        const l = Math.max(0, (issue.line || 1) - 1);
        diagnostics.push(makeDiag(
            new vscode.Range(l, issue.column || 0, l, 1000),
            msg, diagSev, 'SLOP Detector - Patterns', issue.pattern_id,
        ));
    }

    diagnosticCollection.set(uri, diagnostics);
}
