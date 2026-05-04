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
// Public interfaces — mirror FileAnalysis.to_dict() in models.py
// ---------------------------------------------------------------------------

export type SlopStatus =
    | 'clean'
    | 'suspicious'
    | 'inflated_signal'
    | 'dependency_noise'
    | 'critical_deficit';

export type IssueSeverity = 'critical' | 'high' | 'medium' | 'low';

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

export interface ILdrResult {
    ldr_score:        number;
    total_lines:      number;
    logic_lines:      number;
    empty_lines:      number;
    grade:            string;
    is_abc_interface: boolean;
    is_type_stub:     boolean;
    is_packaging_init: boolean;
}

export interface IInflationResult {
    inflation_score:  number;
    jargon_count:     number;
    avg_complexity:   number;
    status:           string;
    jargon_found:     string[];
    jargon_details:   unknown[];
    justified_jargon: string[];
    is_config_file:   boolean;
}

export interface IDdcResult {
    usage_ratio:           number;
    grade:                 string;
    imported:              string[];
    actually_used:         string[];
    unused:                string[];
    fake_imports:          string[];
    type_checking_imports: string[];
}

export interface ISlopReport {
    file_path:      string;
    deficit_score:  number;
    status:         SlopStatus;
    ldr:            ILdrResult;
    inflation:      IInflationResult;
    ddc:            IDdcResult;
    warnings:       string[];
    pattern_issues: ISlopPattern[];
    // Optional — present only when non-empty
    docstring_inflation?: unknown;
    hallucination_deps?:  unknown;
    context_jargon?:      unknown;
    ignored_functions?:   unknown[];
    ml_score?:            { slop_probability: number; label: string; [k: string]: unknown };
    dcf?:                 Record<string, number>;
}

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
