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

export function isFlaggedResult(result: any): boolean {
    return (result?.deficit_score || 0) >= 30 || result?.status !== 'clean';
}

function syncUiContext(): void {
    const flagged = [...fileResults.values()].some((r) => isFlaggedResult(r));
    const analyzed = fileResults.size > 0;
    void vscode.commands.executeCommand('setContext', 'slop.hasAnalyzed', analyzed);
    void vscode.commands.executeCommand('setContext', 'slop.isClean', analyzed && !flagged);
}

export function updateFileResult(filePath: string, result: any): void {
    fileResults.set(filePath, result);
    syncUiContext();
    _treeRefresh?.();
    _codeLensRefresh?.();
}

export function replaceFileResults(results: any[]): void {
    fileResults.clear();
    for (const result of results) {
        if (result?.file_path) {
            fileResults.set(result.file_path, result);
        }
    }
    syncUiContext();
    _treeRefresh?.();
    _codeLensRefresh?.();
}
