import * as vscode from 'vscode';
import * as path from 'path';
import { fileResults } from './state';

type ItemType = 'empty' | 'file' | 'metric' | 'issue';

class SlopItem extends vscode.TreeItem {
    constructor(
        label: string,
        collapsibleState: vscode.TreeItemCollapsibleState,
        public readonly itemType: ItemType,
        public readonly filePath?: string,
        public readonly issue?: any,
    ) {
        super(label, collapsibleState);
    }
}

export class SlopTreeProvider implements vscode.TreeDataProvider<SlopItem> {
    private _onChange = new vscode.EventEmitter<SlopItem | undefined>();
    readonly onDidChangeTreeData = this._onChange.event;

    refresh(): void { this._onChange.fire(undefined); }

    getTreeItem(el: SlopItem): vscode.TreeItem { return el; }

    getChildren(el?: SlopItem): SlopItem[] {
        if (!el) { return this._rootItems(); }
        if (el.itemType === 'file' && el.filePath) { return this._childrenOf(el.filePath); }
        return [];
    }

    private _rootItems(): SlopItem[] {
        const entries = [...fileResults.entries()]
            .filter(([, r]) => (r.deficit_score || 0) >= 0)
            .sort(([, a], [, b]) => (b.deficit_score || 0) - (a.deficit_score || 0));

        if (entries.length === 0) {
            const placeholder = new SlopItem(
                'Run "Analyze File" or "Analyze Workspace" to see results.',
                vscode.TreeItemCollapsibleState.None, 'empty',
            );
            placeholder.iconPath = new vscode.ThemeIcon('info');
            return [placeholder];
        }

        return entries.map(([fp, r]) => this._fileItem(fp, r));
    }

    private _fileItem(filePath: string, result: any): SlopItem {
        const score  = result.deficit_score || 0;
        const status = result.status || 'unknown';
        const issues = (result.pattern_issues ?? []).length;

        const item = new SlopItem(
            path.basename(filePath),
            issues > 0
                ? vscode.TreeItemCollapsibleState.Collapsed
                : vscode.TreeItemCollapsibleState.None,
            'file', filePath,
        );
        item.description = `${score.toFixed(1)}  ${status.toUpperCase()}`;
        item.tooltip     = `${filePath}\nDeficit: ${score.toFixed(1)}/100  Issues: ${issues}`;
        item.iconPath    = score >= 50
            ? new vscode.ThemeIcon('error',   new vscode.ThemeColor('errorForeground'))
            : score >= 30
            ? new vscode.ThemeIcon('warning', new vscode.ThemeColor('editorWarning.foreground'))
            : new vscode.ThemeIcon('pass',    new vscode.ThemeColor('terminal.ansiGreen'));
        item.command = {
            command: 'vscode.open',
            title: 'Open File',
            arguments: [vscode.Uri.file(filePath)],
        };
        item.contextValue = 'slopFile';
        return item;
    }

    private _childrenOf(filePath: string): SlopItem[] {
        const result = fileResults.get(filePath);
        if (!result) { return []; }

        const issues   = result.pattern_issues ?? [];
        const nCrit    = issues.filter((i: any) => (i.severity ?? '').toLowerCase() === 'critical').length;
        const purity   = Math.exp(-0.5 * nCrit);
        const children: SlopItem[] = [];

        // 4D metric summary row
        const metric = new SlopItem(
            `LDR ${(result.ldr?.ldr_score ?? 0).toFixed(2)}  ` +
            `DDC ${(result.ddc?.usage_ratio ?? 0).toFixed(2)}  ` +
            `Purity ${purity.toFixed(2)}  ` +
            `Infl ${(result.inflation?.inflation_score ?? 0).toFixed(2)}`,
            vscode.TreeItemCollapsibleState.None, 'metric', filePath,
        );
        metric.iconPath = new vscode.ThemeIcon('graph-line');
        metric.tooltip  = '4D GQG dimensions: LDR | DDC usage | Purity (exp(-0.5*critical)) | Inflation';
        children.push(metric);

        // Individual pattern issues, CRITICAL first
        const sorted = [...issues].sort((a: any, b: any) => {
            const order: Record<string, number> = { critical: 0, high: 1, medium: 2, low: 3 };
            return (order[a.severity?.toLowerCase() ?? 'medium'] ?? 2)
                 - (order[b.severity?.toLowerCase() ?? 'medium'] ?? 2);
        });

        for (const issue of sorted) {
            const sev  = (issue.severity ?? 'medium').toLowerCase();
            const line = issue.line || 1;
            const it   = new SlopItem(
                `${issue.pattern_id}  L${line}`,
                vscode.TreeItemCollapsibleState.None, 'issue', filePath, issue,
            );
            it.description  = issue.message?.slice(0, 55) ?? '';
            it.tooltip      = issue.suggestion
                ? `${issue.message}\n→ Suggestion: ${issue.suggestion}`
                : (issue.message ?? '');
            it.iconPath     = sev === 'critical' ? new vscode.ThemeIcon('error')
                            : sev === 'high'     ? new vscode.ThemeIcon('warning')
                            :                      new vscode.ThemeIcon('info');
            it.command = {
                command: 'vscode.open',
                title: 'Go to issue',
                arguments: [
                    vscode.Uri.file(filePath),
                    { selection: new vscode.Range(line - 1, 0, line - 1, 0) },
                ],
            };
            it.contextValue = sev === 'critical' ? 'slopIssueCritical' : 'slopIssue';
            children.push(it);
        }

        return children;
    }
}
