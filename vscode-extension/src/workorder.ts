/** Pure text handling of the backend's AI work order (`--format ai-md`); no
 *  VS Code API, so it is testable on real backend output. */

/** One item of a work order, cut from the backend's own document: its header,
 *  every contract section, the VERIFY question of its rule, its W block and the
 *  response form. Nothing is reworded here. undefined when the work order has
 *  no block for this rule at this line. */
export function workOrderForItem(doc: string, fileName: string, line: number, rule: string): string | undefined {
    const lines = doc.replace(/\r\n/g, '\n').split('\n');
    // The work order of a one-file scan: every item is in that file. A JS/TS or
    // Go file scanned alone is located as "." by the 3.14.0 backend (its header
    // `target:` and the item's bound_to still name the file).
    const at = [`at [FACT]: ${fileName}:${line + 1}`, `at [FACT]: .:${line + 1}`];
    const start = lines.findIndex((l, i) =>
        /^### W\d+ \S+ (FINDING|REVIEW_CANDIDATE) /.test(l) && l.split(' ')[4] === rule &&
        at.includes(lines[i + 1] ?? ''));
    if (start < 0) { return undefined; }
    let end = start + 1;
    while (end < lines.length && !/^### W\d+ /.test(lines[end]) && !/^## /.test(lines[end])) { end++; }
    const section = (name: string) => {
        const at = lines.findIndex((l) => l.startsWith(`## ${name}`));
        if (at < 0) { return []; }
        let to = at + 1;
        while (to < lines.length && !lines[to].startsWith('## ')) { to++; }
        return lines.slice(at, to);
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
        '## WORK-ORDER',
        ...lines.slice(start, end).filter((l, i, all) => i < all.length - 1 || l.trim()), '',
        ...section('RESPONSE-FORM'),
    ].join('\n').replace(/\n{3,}/g, '\n\n').trim() + '\n';
}
