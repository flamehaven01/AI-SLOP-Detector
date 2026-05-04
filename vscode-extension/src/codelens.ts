import * as vscode from 'vscode';
import { fileResults } from './state';

// Patterns that map to specific functions — surface as per-function CodeLens
const FUNCTION_PATTERNS = new Set([
    'god_function', 'nested_complexity', 'function_clone_cluster',
    'phantom_import', 'empty_except', 'lint_escape',
]);

export class SlopCodeLensProvider implements vscode.CodeLensProvider {
    private _onChange = new vscode.EventEmitter<void>();
    readonly onDidChangeCodeLenses = this._onChange.event;

    refresh(): void { this._onChange.fire(); }

    provideCodeLenses(document: vscode.TextDocument): vscode.CodeLens[] {
        if (!vscode.workspace.getConfiguration('slopDetector').get('enableCodeLens', true)) {
            return [];
        }

        const result = fileResults.get(document.uri.fsPath);
        if (!result) { return []; }

        const lenses: vscode.CodeLens[] = [];
        const score   = result.deficit_score || 0;
        const issues  = result.pattern_issues ?? [];
        const nCrit   = issues.filter((i: any) => (i.severity ?? '').toLowerCase() === 'critical').length;

        // File-level summary at line 0 — click to re-analyze
        const icon    = score >= 50 ? '$(error)' : score >= 30 ? '$(warning)' : '$(pass)';
        const summary = nCrit > 0
            ? `${nCrit} CRITICAL`
            : issues.length > 0 ? `${issues.length} issues` : 'clean';
        lenses.push(new vscode.CodeLens(new vscode.Range(0, 0, 0, 0), {
            title:   `${icon} SLOP ${score.toFixed(1)} — ${summary}`,
            command: 'slop-detector.analyzeFile',
            tooltip: `Re-analyze file  |  ` +
                `LDR: ${(result.ldr?.ldr_score ?? 0).toFixed(3)}  ` +
                `DDC: ${(result.ddc?.usage_ratio ?? 0).toFixed(3)}  ` +
                `Inflation: ${(result.inflation?.inflation_score ?? 0).toFixed(3)}`,
        }));

        // Per-function/pattern lenses — group issues by line
        const byLine = new Map<number, any[]>();
        for (const issue of issues) {
            if (!FUNCTION_PATTERNS.has(issue.pattern_id)) { continue; }
            const l = Math.max(0, (issue.line || 1) - 1);
            if (!byLine.has(l)) { byLine.set(l, []); }
            byLine.get(l)!.push(issue);
        }

        for (const [line, lineIssues] of byLine) {
            if (line === 0) { continue; }   // already covered by summary lens
            const topSev = lineIssues.some((i: any) => i.severity?.toLowerCase() === 'critical')
                ? 'critical'
                : lineIssues.some((i: any) => i.severity?.toLowerCase() === 'high')
                ? 'high' : 'medium';
            const ico    = topSev === 'critical' ? '$(error)'
                         : topSev === 'high'     ? '$(warning)' : '$(info)';
            const title  = lineIssues.length === 1
                ? `${ico} ${lineIssues[0].pattern_id}: ${(lineIssues[0].message ?? '').slice(0, 55)}`
                : `${ico} ${lineIssues.map((i: any) => i.pattern_id).join(' · ')} (${lineIssues.length})`;
            const tip    = lineIssues
                .map((i: any) => i.suggestion
                    ? `[${i.pattern_id}] ${i.suggestion}` : `[${i.pattern_id}] ${i.message ?? ''}`)
                .join('\n');

            lenses.push(new vscode.CodeLens(new vscode.Range(line, 0, line, 0), {
                title, command: 'slop-detector.showOutput', tooltip: tip,
            }));
        }

        return lenses;
    }
}
