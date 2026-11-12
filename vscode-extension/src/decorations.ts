import * as vscode from 'vscode';
import { fileResults } from './state';
import { LineItem, SEVERITY_LABEL, lineItems } from './findings';
import { bindingOf } from './binding';

type Level = LineItem['severity'];
const LEVELS: Level[] = ['critical', 'high', 'medium', 'low', 'review'];

// Line tint, left bar and overview-ruler mark per level; the active line (the
// cursor or a selection on a flagged line) gets a stronger tint and a frame.
const COLORS: Record<Level, { bar: string; tint: string; strong: string }> = {
    critical: { bar: '#e5484d', tint: 'rgba(229, 72, 77, 0.18)', strong: 'rgba(229, 72, 77, 0.32)' },
    high:     { bar: '#f2711c', tint: 'rgba(242, 113, 28, 0.16)', strong: 'rgba(242, 113, 28, 0.30)' },
    medium:   { bar: '#e0b000', tint: 'rgba(224, 176, 0, 0.13)', strong: 'rgba(224, 176, 0, 0.27)' },
    low:      { bar: '#8b949e', tint: 'rgba(139, 148, 158, 0.10)', strong: 'rgba(139, 148, 158, 0.22)' },
    review:   { bar: '#8e6cd8', tint: 'rgba(142, 108, 216, 0.15)', strong: 'rgba(142, 108, 216, 0.30)' },
};
const INLINE_CHARS = 110;

function lineType(level: Level, active: boolean, stale = false): vscode.TextEditorDecorationType {
    const c = COLORS[level];
    // A file changed since its analysis: the same colour, faint and dotted,
    // so a line that may have moved is not presented as exact.
    if (stale) {
        return vscode.window.createTextEditorDecorationType({
            isWholeLine: true,
            backgroundColor: 'rgba(139, 148, 158, 0.06)',
            borderColor: c.bar,
            borderStyle: 'dotted',
            borderWidth: '0 0 0 2px',
            rangeBehavior: vscode.DecorationRangeBehavior.ClosedClosed,
        });
    }
    return vscode.window.createTextEditorDecorationType({
        isWholeLine: true,
        backgroundColor: active ? c.strong : c.tint,
        borderColor: c.bar,
        borderStyle: level === 'review' ? 'dashed' : 'solid',
        borderWidth: active ? '1px 1px 1px 5px' : '0 0 0 4px',
        overviewRulerColor: c.bar,
        overviewRulerLane: vscode.OverviewRulerLane.Right,
        rangeBehavior: vscode.DecorationRangeBehavior.ClosedClosed,
    });
}

export class LineHighlighter implements vscode.Disposable {
    private readonly normal = new Map<Level, vscode.TextEditorDecorationType>();
    private readonly active = new Map<Level, vscode.TextEditorDecorationType>();
    private readonly stale = new Map<Level, vscode.TextEditorDecorationType>();
    private statusMessage: vscode.Disposable | undefined;

    constructor() {
        for (const level of LEVELS) {
            this.normal.set(level, lineType(level, false));
            this.active.set(level, lineType(level, true));
            this.stale.set(level, lineType(level, false, true));
        }
    }

    private allTypes(): vscode.TextEditorDecorationType[] {
        return [...this.normal.values(), ...this.active.values(), ...this.stale.values()];
    }

    /** Redraw every visible editor (after an analysis or a settings change). */
    refreshAll(): void {
        for (const editor of vscode.window.visibleTextEditors) { this.refresh(editor); }
    }

    refresh(editor: vscode.TextEditor | undefined): void {
        if (!editor) { return; }
        const cfg = vscode.workspace.getConfiguration('slopDetector');
        const enabled = cfg.get<boolean>('highlightLines', true);
        const inline = cfg.get<boolean>('showInlineWarnings', true);
        const showHollow = cfg.get<boolean>('showHollowCandidates', true);
        const result = fileResults.get(editor.document.uri.fsPath);
        const items = enabled && result
            ? lineItems(result).filter((i) => showHollow || i.kind === 'finding')
            : [];
        const changed = bindingOf(editor.document.uri.fsPath) === 'CHANGED';
        const activeLines = new Set(editor.selections.map((s) => s.active.line));
        const byType = new Map<vscode.TextEditorDecorationType, vscode.DecorationOptions[]>();
        for (const t of this.allTypes()) { byType.set(t, []); }

        const firstOnLine = new Map<number, LineItem[]>();
        for (const item of items) {
            if (item.line >= editor.document.lineCount) { continue; }
            const list = firstOnLine.get(item.line) ?? [];
            list.push(item);
            firstOnLine.set(item.line, list);
        }
        for (const [line, onLine] of firstOnLine) {
            const top = onLine[0]; // most severe first
            const isActive = activeLines.has(line);
            const type = (changed ? this.stale : isActive ? this.active : this.normal).get(top.severity)!;
            const option: vscode.DecorationOptions = { range: editor.document.lineAt(line).range };
            if (inline || isActive) {
                option.renderOptions = { after: this.inlineText(onLine, isActive, changed) };
            }
            byType.get(type)!.push(option);
        }
        for (const [type, options] of byType) { editor.setDecorations(type, options); }
        this.showActiveInStatusBar(firstOnLine.get(editor.selection.active.line));
    }

    private inlineText(
        onLine: LineItem[], active: boolean, changed: boolean,
    ): vscode.ThemableDecorationAttachmentRenderOptions {
        const top = onLine[0];
        const more = onLine.length > 1 ? `  (+${onLine.length - 1})` : '';
        let text = `${SEVERITY_LABEL[top.severity]} ${top.rule}: ${top.message}`;
        if (text.length > INLINE_CHARS) { text = text.slice(0, INLINE_CHARS - 3) + '...'; }
        if (changed) { text = `(file changed - analyze again) ${text}`; }
        return {
            contentText: `  ■ ${text}${more}${active ? '   (hover for the fix)' : ''}`,
            color: changed ? '#8b949e' : COLORS[top.severity].bar,
            fontStyle: active ? 'normal' : 'italic',
            fontWeight: active ? 'bold' : 'normal',
            margin: '0 0 0 1.5em',
        };
    }

    private showActiveInStatusBar(onLine: LineItem[] | undefined): void {
        this.statusMessage?.dispose();
        this.statusMessage = undefined;
        if (!onLine || onLine.length === 0) { return; }
        const top = onLine[0];
        this.statusMessage = vscode.window.setStatusBarMessage(
            `$(search) SLOP ${SEVERITY_LABEL[top.severity]} ${top.rule}` +
            (onLine.length > 1 ? ` (+${onLine.length - 1} on this line)` : ''),
        );
    }

    dispose(): void {
        this.statusMessage?.dispose();
        for (const t of this.allTypes()) { t.dispose(); }
    }
}
