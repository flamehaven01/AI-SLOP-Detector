import * as vscode from 'vscode';

export let diagnosticCollection: vscode.DiagnosticCollection;
export let statusBarItem: vscode.StatusBarItem;
export let outputChannel: vscode.OutputChannel;
export let lintOnTypeTimer: ReturnType<typeof setTimeout> | undefined;

export function initState(
    collection: vscode.DiagnosticCollection,
    bar: vscode.StatusBarItem,
    channel: vscode.OutputChannel,
): void {
    diagnosticCollection = collection;
    statusBarItem = bar;
    outputChannel = channel;
}

export function setLintTimer(t: ReturnType<typeof setTimeout> | undefined): void {
    lintOnTypeTimer = t;
}

// P3/P4: per-file analysis results — shared by TreeView + CodeLens
export const fileResults: Map<string, any> = new Map();
let _treeRefresh:     (() => void) | undefined;
let _codeLensRefresh: (() => void) | undefined;

export function setTreeRefreshCallback(cb: () => void): void     { _treeRefresh = cb; }
export function setCodeLensRefreshCallback(cb: () => void): void { _codeLensRefresh = cb; }

export function updateFileResult(filePath: string, result: any): void {
    fileResults.set(filePath, result);
    // Drive state-aware UI (viewsWelcome + view/title menus). A file counts as
    // flagged at the SUSPICIOUS band (deficit >= 30); see the severity tokens
    // in the presentation contract.
    const flagged = [...fileResults.values()].some((r) => (r.deficit_score || 0) >= 30);
    void vscode.commands.executeCommand('setContext', 'slop.hasAnalyzed', true);
    void vscode.commands.executeCommand('setContext', 'slop.isClean', !flagged);
    _treeRefresh?.();
    _codeLensRefresh?.();
}
