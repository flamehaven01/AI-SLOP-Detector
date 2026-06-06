/**
 * Runtime schema contracts for slop-detector CLI JSON output.
 *
 * Validates the --json payload at the extension boundary so field-access
 * failures (wrong types, missing keys, version skew) surface as clear
 * diagnostic messages rather than silent NaN or undefined crashes.
 *
 * No external validation library — all guards are handwritten type predicates.
 */

// ---------------------------------------------------------------------------
// Public types — the data contract is owned by the `ai-slop-detector` npm
// package (types.d.ts, generated from models.py). We re-export it here rather
// than hand-maintaining a parallel copy that can drift.
// ---------------------------------------------------------------------------

import type { FileAnalysisOutput, SlopStatus as NpmSlopStatus } from 'ai-slop-detector';

export type SlopStatus = NpmSlopStatus;
export type IssueSeverity = 'critical' | 'high' | 'medium' | 'low';

/** The extension's stronger view of a pattern issue. The npm contract types
 *  `pattern_issues` loosely (JsonObject | string); this is what the renderers
 *  actually read. */
export interface ISlopPattern {
    pattern_id:  string;
    severity:    IssueSeverity;
    axis:        string;
    file:        string;
    line:        number;
    column:      number;
    message:     string;
    code?:       string | null;
    suggestion?: string | null;
}

export type ISlopReport = FileAnalysisOutput;

// ---------------------------------------------------------------------------
// Parse result — discriminated union (no exceptions thrown by parseSlopReport)
// ---------------------------------------------------------------------------

export interface SchemaError {
    field:    string;
    expected: string;
    got:      string;
}

export type ParseResult<T> =
    | { ok: true;  value: T }
    | { ok: false; error: SchemaError };

// ---------------------------------------------------------------------------
// Internal helpers
// ---------------------------------------------------------------------------

function typeTag(v: unknown): string {
    if (v === null)        { return 'null'; }
    if (Array.isArray(v)) { return 'array'; }
    return typeof v;
}

function checkString(obj: Record<string, unknown>, key: string): SchemaError | null {
    return typeof obj[key] === 'string'
        ? null
        : { field: key, expected: 'string', got: typeTag(obj[key]) };
}

function checkNumber(obj: Record<string, unknown>, key: string): SchemaError | null {
    return typeof obj[key] === 'number'
        ? null
        : { field: key, expected: 'number', got: typeTag(obj[key]) };
}

function checkArray(obj: Record<string, unknown>, key: string): SchemaError | null {
    return Array.isArray(obj[key])
        ? null
        : { field: key, expected: 'array', got: typeTag(obj[key]) };
}

function checkObject(obj: Record<string, unknown>, key: string): SchemaError | null {
    const v = obj[key];
    return (v && typeof v === 'object' && !Array.isArray(v))
        ? null
        : { field: key, expected: 'object', got: typeTag(v) };
}

const VALID_STATUSES = new Set<string>([
    'clean', 'suspicious', 'inflated_signal', 'dependency_noise', 'critical_deficit',
]);

function validatePattern(raw: unknown, idx: number): SchemaError | null {
    if (!raw || typeof raw !== 'object' || Array.isArray(raw)) {
        return { field: `pattern_issues[${idx}]`, expected: 'object', got: typeTag(raw) };
    }
    const p = raw as Record<string, unknown>;
    for (const key of ['pattern_id', 'severity', 'message'] as const) {
        if (typeof p[key] !== 'string') {
            return {
                field: `pattern_issues[${idx}].${key}`,
                expected: 'string',
                got: typeTag(p[key]),
            };
        }
    }
    if (typeof p['line'] !== 'number') {
        return { field: `pattern_issues[${idx}].line`, expected: 'number', got: typeTag(p['line']) };
    }
    return null;
}

// ---------------------------------------------------------------------------
// Public entry point — returns ParseResult, never throws
// ---------------------------------------------------------------------------

export function parseSlopReport(data: unknown): ParseResult<ISlopReport> {
    if (!data || typeof data !== 'object' || Array.isArray(data)) {
        return { ok: false, error: { field: 'root', expected: 'object', got: typeTag(data) } };
    }
    const d = data as Record<string, unknown>;

    // Required top-level fields
    const topChecks = [
        checkString(d, 'file_path'),
        checkNumber(d, 'deficit_score'),
        checkObject(d, 'ldr'),
        checkObject(d, 'inflation'),
        checkObject(d, 'ddc'),
        checkArray(d,  'warnings'),
        checkArray(d,  'pattern_issues'),
    ];
    for (const err of topChecks) {
        if (err) { return { ok: false, error: err }; }
    }

    // status must be a known enum value
    if (typeof d['status'] !== 'string' || !VALID_STATUSES.has(d['status'])) {
        return {
            ok: false,
            error: {
                field:    'status',
                expected: [...VALID_STATUSES].join(' | '),
                got:      String(d['status']),
            },
        };
    }

    // ldr.ldr_score must be numeric (protects Math.exp / toFixed calls downstream)
    const ldr = d['ldr'] as Record<string, unknown>;
    if (typeof ldr['ldr_score'] !== 'number') {
        return {
            ok: false,
            error: { field: 'ldr.ldr_score', expected: 'number', got: typeTag(ldr['ldr_score']) },
        };
    }

    // Validate each pattern_issues entry
    const patterns = d['pattern_issues'] as unknown[];
    for (let i = 0; i < patterns.length; i++) {
        const err = validatePattern(patterns[i], i);
        if (err) { return { ok: false, error: err }; }
    }

    return { ok: true, value: data as ISlopReport };
}
