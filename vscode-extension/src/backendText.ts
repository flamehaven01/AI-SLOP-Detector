/** Reading the backend's human text output where no JSON exists, and path
 *  checks on what it reports; no VS Code API, so it is tested on real backend
 *  output. */

import * as path from 'path';

export interface GateDecision {
    status: string;          // PASS, HALT, ...
    allowed: boolean;
    metrics: string;         // "sr9=0.6667  di2=1.0000  jsd=1.0000  ove=0.7800"
    notes: string[];         // Capability, Not judged, Halt, Recommend lines
    halt?: string;
    block: string;           // the whole [Gate Decision] block, as printed
}

/** The `[Gate Decision]` block `--gate` prints after the analysis (the backend
 *  has no JSON field for it, with or without --json): the indented lines right
 *  after the header. The backend's gate has two states, PASS with Allowed True
 *  and HALT with Allowed False (gate/slop_gate.py); anything else, a missing
 *  line or a contradiction such as HALT with Allowed True, gives undefined
 *  (never guessed). */
export function parseGateDecision(stdout: string): GateDecision | undefined {
    const lines = stdout.replace(/\r\n/g, '\n').split('\n');
    const start = lines.findIndex((l) => l.trim() === '[Gate Decision]');
    if (start < 0) { return undefined; }
    const body: string[] = [];
    for (const l of lines.slice(start + 1)) {
        if (!l.startsWith('  ')) { break; }
        body.push(l.trim());
    }
    const field = (name: string) => body.find((l) => l.startsWith(name))?.split(':').slice(1).join(':').trim();
    const status = field('Status');
    const allowed = field('Allowed');
    const consistent = (status === 'PASS' && allowed === 'True') || (status === 'HALT' && allowed === 'False');
    if (!consistent) { return undefined; }
    return {
        status,
        allowed: allowed === 'True',
        metrics: body.find((l) => l.startsWith('sr9=')) ?? '',
        notes: body.filter((l) => /^(Capability|Not judged|Halt|Recommend)/.test(l)),
        halt: field('Halt'),
        block: ['[Gate Decision]', ...body.map((l) => `  ${l}`)].join('\n'),
    };
}

/** Whether `target` is `folder` or inside it, compared case-insensitively on
 *  Windows (both are absolute, already resolved paths). */
export function isInside(target: string, folder: string, platform: string = process.platform): boolean {
    const p = platform === 'win32' ? path.win32 : path.posix;
    const norm = (s: string) => (platform === 'win32' ? p.normalize(s).toLowerCase() : p.normalize(s));
    const rel = p.relative(norm(folder), norm(target));
    return rel === '' || (!rel.startsWith('..') && !p.isAbsolute(rel));
}
