import * as vscode from 'vscode';
import { fileResults } from './state';
import { LineItem, SEVERITY_LABEL, channelLine, itemsOnLine } from './findings';
import { bindingOf } from './binding';

// Badge colours for the hover (VS Code renders a span's color /
// background-color in hovers; nothing else of the style attribute).
const BADGE: Record<string, [string, string]> = {
    critical: ['#ffffff', '#b3261e'],
    high:     ['#ffffff', '#c2410c'],
    medium:   ['#1d1d1d', '#e0b000'],
    low:      ['#ffffff', '#5b6670'],
    review:   ['#ffffff', '#6b3fa0'],
};
const ICON: Record<string, string> = {
    critical: '$(error)', high: '$(warning)', medium: '$(info)', low: '$(circle-small-filled)', review: '$(search)',
};

function escapeMd(text: string): string {
    return text.replace(/[\\`*_{}[\]()#+\-.!|<>]/g, (c) => `\\${c}`);
}

function commandLink(label: string, command: string, args: unknown[]): string {
    return `[${label}](command:${command}?${encodeURIComponent(JSON.stringify(args))})`;
}

function itemBlock(item: LineItem, filePath: string): string {
    const [fg, bg] = BADGE[item.severity];
    const badge = `<span style="color:${fg};background-color:${bg};">&nbsp;${SEVERITY_LABEL[item.severity]}&nbsp;</span>`;
    const lines = [`${ICON[item.severity]} ${badge} &nbsp;\`${item.rule}\``, '', escapeMd(item.message)];
    if (item.promise) {
        const p = item.promise;
        lines.push('', `$(quote) **Docstring promise** (${escapeMd(p.kind)}): _"${escapeMd(p.text)}"_`,
            '', `**Needs:** ${escapeMd(p.lookedFor)} &nbsp;·&nbsp; **Found:** ${escapeMd(p.found)}`);
    }
    if (item.kind === 'candidate') {
        lines.push('', '_Not scored: evidence for a review, not a verdict._');
        if (item.suggestion) { lines.push('', `**Resolve:** ${escapeMd(item.suggestion)}`); }
    } else if (item.suggestion) {
        lines.push('', `**Fix:** ${escapeMd(item.suggestion)}`);
    }
    lines.push('', [
        commandLink('$(copy) Copy work order for an AI agent','slop-detector.copyItemForAgent', [filePath, item.line, item.rule]),
        commandLink('$(preview) Open report', 'slop-detector.openReport', []),
    ].join(' &nbsp;|&nbsp; '));
    return lines.join('\n');
}

/** Hover on a line the last analysis flagged: what, how severe, how to fix. */
export class SlopHoverProvider implements vscode.HoverProvider {
    provideHover(document: vscode.TextDocument, position: vscode.Position): vscode.Hover | undefined {
        const result = fileResults.get(document.uri.fsPath);
        if (!result) { return undefined; }
        const items = itemsOnLine(result, position.line);
        if (items.length === 0) { return undefined; }
        const md = new vscode.MarkdownString(undefined, true);
        md.supportHtml = true;
        md.isTrusted = {
            enabledCommands: ['slop-detector.copyItemForAgent', 'slop-detector.openReport', 'slop-detector.analyzeFile'],
        };
        md.appendMarkdown(`**AI SLOP Detector** &nbsp;line ${position.line + 1}\n\n`);
        if (bindingOf(document.uri.fsPath) === 'CHANGED') {
            md.appendMarkdown(
                '$(history) **The file changed after this analysis**: these lines may have moved. ' +
                commandLink('$(refresh) Analyze again', 'slop-detector.analyzeFile', []) + '\n\n',
            );
        }
        md.appendMarkdown('---\n\n');
        md.appendMarkdown(items.map((i) => itemBlock(i, document.uri.fsPath)).join('\n\n---\n\n'));
        const score = typeof result.deficit_score === 'number' ? result.deficit_score.toFixed(1) : 'N/A';
        md.appendMarkdown(
            `\n\n---\n\n$(pulse) File score ${score}/100 ${String(result.status ?? '').toUpperCase()}` +
            ` &nbsp;|&nbsp; ${escapeMd(channelLine(result))}`,
        );
        const line = document.lineAt(position.line);
        return new vscode.Hover(md, line.range);
    }
}
