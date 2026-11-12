/** One list of what a file result reports, located by line: the single
 *  source for diagnostics, hover, line highlights and the tree. */

export type Severity = 'critical' | 'high' | 'medium' | 'low';

/** A docstring promise the body cannot keep (backend 3.14+ claim channel). */
export interface DocPromise {
    text: string;          // the docstring sentence
    kind: string;          // computed_result, parallel, validation, ...
    lookedFor: string;     // what the body would need
    found: string;         // what the detector found instead
}

export interface LineItem {
    kind: 'finding' | 'candidate';
    rule: string;
    severity: Severity | 'review';
    line: number;          // 0-based
    column: number;
    message: string;
    suggestion: string;
    promise?: DocPromise;   // a candidate's own promise, or one merged into a finding
}

const ORDER: Record<string, number> = { critical: 0, high: 1, medium: 2, low: 3, review: 4 };

function severityOf(raw: unknown): Severity {
    const s = String(raw ?? 'medium').toLowerCase();
    return (s === 'critical' || s === 'high' || s === 'low') ? s : 'medium';
}

function promiseOf(c: any): DocPromise {
    return {
        text: String(c.promise ?? ''),
        kind: String(c.claim_kind ?? ''),
        lookedFor: String(c.looked_for ?? ''),
        found: String(c.why ?? ''),
    };
}

/** Pattern findings, hollow candidates and docstring-promise candidates, most
 *  severe first. A promise the backend merged into a finding (same_cause_as)
 *  is shown on that finding, not as a second item. */
export function lineItems(result: any): LineItem[] {
    const items: LineItem[] = [];
    const claims: any[] = Array.isArray(result?.claim_findings) ? result.claim_findings : [];
    for (const issue of result?.pattern_issues ?? []) {
        if (typeof issue !== 'object' || issue === null) { continue; }
        const rule = String(issue.pattern_id ?? 'pattern');
        const merged = claims.find((c) => c.line === issue.line && (c.same_cause_as ?? []).includes(rule));
        items.push({
            kind: 'finding',
            rule,
            severity: severityOf(issue.severity),
            line: Math.max(0, (issue.line || 1) - 1),
            column: issue.column || 0,
            message: String(issue.message ?? 'Pattern issue detected'),
            suggestion: String(issue.suggestion ?? ''),
            promise: merged ? promiseOf(merged) : undefined,
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
    for (const c of claims) {
        if ((c.same_cause_as ?? []).length > 0) { continue; }
        items.push({
            kind: 'candidate',
            rule: String(c.kind ?? 'claim_without_mechanism'),
            severity: 'review',
            line: Math.max(0, (c.line || 1) - 1),
            column: 0,
            message: `${c.function}: promises "${c.promise}" (${c.claim_kind}); ${c.why}`,
            suggestion: String(c.resolves ?? ''),
            promise: promiseOf(c),
        });
    }
    return items.sort((a, b) => (ORDER[a.severity] - ORDER[b.severity]) || (a.line - b.line));
}

/** Items on one 0-based line, most severe first. */
export function itemsOnLine(result: any, line: number): LineItem[] {
    return lineItems(result).filter((i) => i.line === line);
}

/** Review candidates of a result (hollow and docstring promises). */
export function candidateCount(result: any): number {
    return lineItems(result).filter((i) => i.kind === 'candidate').length;
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

/** Measurement state per channel, as the backend reports it. A channel that
 *  did not run reads "not measured" or "n/a", never a count of 0. */
export function channelStates(result: any): { name: string; state: string }[] {
    const pattern = (result?.pattern_errors ?? []).length > 0 ? 'PARTIAL' : 'COMPLETE';
    const state = (cov: any) => {
        const s = cov?.state;
        if (!s) { return 'n/a'; }
        return s === 'UNMEASURED' ? 'not measured' : s;
    };
    return [
        { name: 'pattern', state: pattern },
        { name: 'hollow', state: state(result?.semantic_coverage) },
        { name: 'promises', state: state(result?.claim_coverage) },
    ];
}

export function channelLine(result: any): string {
    return channelStates(result).map((c) => `${c.name} ${c.state}`).join(' · ');
}

export const SEVERITY_LABEL: Record<string, string> = {
    critical: 'CRITICAL', high: 'HIGH', medium: 'MEDIUM', low: 'LOW', review: 'REVIEW',
};
