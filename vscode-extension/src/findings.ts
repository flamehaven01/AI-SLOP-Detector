/** One list of what a file result reports, located by line: the single
 *  source for diagnostics, hover, line highlights and the tree. */

export type Severity = 'critical' | 'high' | 'medium' | 'low';

export interface LineItem {
    kind: 'finding' | 'candidate';
    rule: string;
    severity: Severity | 'review';
    line: number;          // 0-based
    column: number;
    message: string;
    suggestion: string;
}

const ORDER: Record<string, number> = { critical: 0, high: 1, medium: 2, low: 3, review: 4 };

function severityOf(raw: unknown): Severity {
    const s = String(raw ?? 'medium').toLowerCase();
    return (s === 'critical' || s === 'high' || s === 'low') ? s : 'medium';
}

/** Pattern findings and hollow review candidates, most severe first. */
export function lineItems(result: any): LineItem[] {
    const items: LineItem[] = [];
    for (const issue of result?.pattern_issues ?? []) {
        if (typeof issue !== 'object' || issue === null) { continue; }
        items.push({
            kind: 'finding',
            rule: String(issue.pattern_id ?? 'pattern'),
            severity: severityOf(issue.severity),
            line: Math.max(0, (issue.line || 1) - 1),
            column: issue.column || 0,
            message: String(issue.message ?? 'Pattern issue detected'),
            suggestion: String(issue.suggestion ?? ''),
        });
    }
    for (const c of result?.semantic_findings ?? []) {
        items.push({
            kind: 'candidate',
            rule: String(c.kind ?? 'hollow'),
            severity: 'review',
            line: Math.max(0, (c.line || 1) - 1),
            column: 0,
            message: c.evidence ? `${c.function}: ${c.evidence}` : String(c.function ?? ''),
            suggestion: '',
        });
    }
    return items.sort((a, b) => (ORDER[a.severity] - ORDER[b.severity]) || (a.line - b.line));
}

/** Items on one 0-based line, most severe first. */
export function itemsOnLine(result: any, line: number): LineItem[] {
    return lineItems(result).filter((i) => i.line === line);
}

/** What the hollow channel measured, in words; never "0" when not measured. */
export function hollowState(result: any): string {
    const cov = result?.semantic_coverage;
    const state = cov?.state;
    if (!state) { return 'not available (backend before 3.14, or not a Python file)'; }
    if (state === 'SKIPPED') { return 'skipped'; }
    if (state === 'UNMEASURED') { return 'not measured (analysis failed)'; }
    const unknown = cov.effect_states?.EFFECT_UNKNOWN ?? 0;
    const n = (result.semantic_findings ?? []).length;
    return `${n} review candidate(s), not scored - ${cov.functions ?? 0} functions, ${unknown} not decidable`;
}

export const SEVERITY_LABEL: Record<string, string> = {
    critical: 'CRITICAL', high: 'HIGH', medium: 'MEDIUM', low: 'LOW', review: 'HOLLOW REVIEW',
};
