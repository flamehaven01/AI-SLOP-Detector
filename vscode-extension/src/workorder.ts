/** Pure text handling of the backend's AI work order (`--format ai-md`); no
 *  VS Code API, so it is testable on real backend output. */

const ITEM = /^#{3,4} W\d+ \S+ (FINDING|REVIEW_CANDIDATE) /;   // `###` before S2, `####` inside a family since
const FAMILY = /^### G\d+ /;                                      // S2: what the items of one family share

/** One item of a work order, cut from the backend's own document: its header,
 *  every contract section, the VERIFY question of its rule, its file's FILES
 *  row and its family header (backend with S2 families), its W block and the
 *  response form. Nothing is reworded here. undefined when the work order has
 *  no block for this rule at this line. */
export function workOrderForItem(doc: string, fileName: string, line: number, rule: string): string | undefined {
    const lines = doc.replace(/\r\n/g, '\n').split('\n');
    // The work order of a one-file scan: every item is in that file. A JS/TS or
    // Go file scanned alone is located as "." by the 3.14.0 backend (its header
    // `target:` and the item's bound_to still name the file); 3.14.1 writes
    // the file name. Both are accepted.
    const at = [`at [FACT]: ${fileName}:${line + 1}`, `at [FACT]: .:${line + 1}`];
    const start = lines.findIndex((l, i) =>
        ITEM.test(l) && l.split(' ')[4] === rule && at.includes(lines[i + 1] ?? ''));
    if (start < 0) { return undefined; }
    let end = start + 1;
    while (end < lines.length && !ITEM.test(lines[end]) && !/^#{2,3} /.test(lines[end])) { end++; }
    const block = lines.slice(start, end).filter((l, i, all) => i < all.length - 1 || l.trim());
    const section = (name: string) => {
        const from = lines.findIndex((l) => l.startsWith(`## ${name}`));
        if (from < 0) { return []; }
        let to = from + 1;
        while (to < lines.length && !lines[to].startsWith('## ')) { to++; }
        return lines.slice(from, to);
    };
    const header = lines.slice(0, lines.findIndex((l) => l.startsWith('## ')));
    const contract = ['CONTRACT', 'AUTHORITY', 'PRECONDITIONS', 'HARD-STOP', 'FORBID', 'INVARIANTS', 'ALLOWED', 'LIMITS']
        .flatMap((name) => section(name));
    const rules = section('RULES').filter((l, i) => i < 2 || l.startsWith(`- ${rule}:`));
    return [
        ...header.filter((l) => l.trim()),
        'scope: one item of this work order, copied from the VS Code extension',
        '',
        ...contract,
        ...rules, '',
        ...filesRow(lines, block, section('FILES')),
        '## WORK-ORDER',
        ...familyHeader(lines, start),
        ...block, '',
        ...section('RESPONSE-FORM'),
    ].join('\n').replace(/\n{3,}/g, '\n\n').trim() + '\n';
}

/** The FILES section with only the row the item points to (`bound_to [FACT]:
 *  B01 ...`); nothing for a work order without one (before S2). */
function filesRow(lines: string[], block: string[], files: string[]): string[] {
    const ref = block.find((l) => l.startsWith('bound_to [FACT]: B'))?.split(' ')[2];
    const row = ref ? files.find((l) => l.startsWith(`- ${ref} `)) : undefined;
    return row ? [...files.slice(0, 2), row, ''] : [];
}

/** The header of the family the item at `start` belongs to: its `### G..` line
 *  and the lines up to the blank one (shared channel and fix); nothing before S2. */
function familyHeader(lines: string[], start: number): string[] {
    let from = start - 1;
    while (from >= 0 && !FAMILY.test(lines[from]) && !lines[from].startsWith('## ')) { from--; }
    if (from < 0 || !FAMILY.test(lines[from])) { return []; }
    const to = lines.indexOf('', from);
    return [...lines.slice(from, to < 0 ? start : to), ''];
}
