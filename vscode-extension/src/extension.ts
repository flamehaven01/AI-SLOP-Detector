import * as vscode from 'vscode';
import { initState, setLintTimer, lintOnTypeTimer, setTreeRefreshCallback } from './state';
import { analyzeDocument } from './analyzer';
import {
    analyzeCurrentFile, analyzeWorkspace, showFileHistory,
    installGitHook, runCrossFileAnalysis, showHistoryTrends, exportHistory,
} from './commands';
import { autoFixCurrentFile, showGateDecision, initConfig, selfCalibrate } from './calibration';
import { SlopCodeActionProvider, addFileToIgnore } from './codeActions';
import { outputChannel } from './state';
import { SlopTreeProvider } from './treeview';

export function activate(context: vscode.ExtensionContext): void {
    const channel    = vscode.window.createOutputChannel('SLOP Detector');
    const collection = vscode.languages.createDiagnosticCollection('slop-detector');
    const bar        = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Right, 100);

    bar.text = '$(check) SLOP: Ready';
    bar.show();

    initState(collection, bar, channel);
    channel.appendLine('[*] AI SLOP Detector v3.7.1 activated');

    context.subscriptions.push(collection, bar, channel);

    // P3: TreeView sidebar
    const treeProvider = new SlopTreeProvider();
    setTreeRefreshCallback(() => treeProvider.refresh());
    const treeView = vscode.window.createTreeView('slopDetector.fileTree', {
        treeDataProvider: treeProvider,
        showCollapseAll: true,
    });
    context.subscriptions.push(treeView);

    // Core commands
    const cmds: [string, (...args: any[]) => any][] = [
        ['slop-detector.analyzeFile',        analyzeCurrentFile],
        ['slop-detector.analyzeWorkspace',   analyzeWorkspace],
        ['slop-detector.showHistory',        showFileHistory],
        ['slop-detector.installGitHook',     installGitHook],
        ['slop-detector.crossFileAnalysis',  runCrossFileAnalysis],
        ['slop-detector.showHistoryTrends',  showHistoryTrends],
        ['slop-detector.exportHistory',      exportHistory],
        ['slop-detector.autoFix',            autoFixCurrentFile],
        ['slop-detector.showGate',           showGateDecision],
        ['slop-detector.initConfig',         initConfig],
        ['slop-detector.selfCalibrate',      selfCalibrate],
        // P2: Code Action helpers
        ['slop-detector.showOutput',         () => outputChannel.show(true)],
        ['slop-detector.addFileToIgnore',    (relPath: string) => addFileToIgnore(relPath)],
        // P3: TreeView refresh
        ['slop-detector.refreshTree',        () => treeProvider.refresh()],
    ];
    for (const [id, handler] of cmds) {
        context.subscriptions.push(vscode.commands.registerCommand(id, handler));
    }

    // P2: phantom_import / god_function Code Action provider
    context.subscriptions.push(
        vscode.languages.registerCodeActionsProvider(
            [{ language: 'python' }, { language: 'javascript' },
             { language: 'typescript' }, { language: 'go' }],
            new SlopCodeActionProvider(),
            { providedCodeActionKinds: SlopCodeActionProvider.providedCodeActionKinds },
        )
    );

    // Auto-lint on save
    context.subscriptions.push(
        vscode.workspace.onDidSaveTextDocument(document => {
            if (vscode.workspace.getConfiguration('slopDetector').get('lintOnSave')) {
                analyzeDocument(document);
            }
        })
    );

    // Auto-lint on type (1500 ms debounce)
    context.subscriptions.push(
        vscode.workspace.onDidChangeTextDocument(event => {
            if (!vscode.workspace.getConfiguration('slopDetector').get('lintOnType')) { return; }
            if (lintOnTypeTimer !== undefined) { clearTimeout(lintOnTypeTimer); }
            setLintTimer(setTimeout(() => {
                setLintTimer(undefined);
                analyzeDocument(event.document);
            }, 1500));
        })
    );
}

export function deactivate(): void {
    if (lintOnTypeTimer !== undefined) { clearTimeout(lintOnTypeTimer); }
}
