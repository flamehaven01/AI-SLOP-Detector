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
