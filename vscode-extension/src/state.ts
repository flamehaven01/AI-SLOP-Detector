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
    _treeRefresh?.();
    _codeLensRefresh?.();
}
