import * as vscode from 'vscode';
import {
    initState, setLintTimer, lintOnTypeTimer, setTreeRefreshCallback, setCodeLensRefreshCallback,
    setHighlightRefreshCallback, fileResults,
} from './state';
import { analyzeDocument } from './analyzer';
import {
    analyzeCurrentFile, analyzeWorkspace, showFileHistory,
    installGitHook, runCrossFileAnalysis, showHistoryTrends, exportHistory,
} from './commands';
import { autoFixCurrentFile, showGateDecision, initConfig, selfCalibrate } from './calibration';
import { SlopCodeActionProvider, addFileToIgnore, addModuleToAllowlist } from './codeActions';
import { showBreakdownPanel } from './breakdownPanel';
import { showCleanupPanel } from './cleanupPanel';
import { showPulsePanel } from './pulsePanel';
import { showReviewPanel } from './reviewPanel';
import { outputChannel } from './state';
import { SlopTreeProvider } from './treeview';
import { SlopCodeLensProvider } from './codelens';
import { SlopHoverProvider } from './hover';
import { LineHighlighter } from './decorations';
import { copyItemForAgent, exportReport, openReport } from './report';

const LANGUAGES = [{ language: 'python' }, { language: 'javascript' }, { language: 'typescript' }, { language: 'go' }];

export function activate(context: vscode.ExtensionContext): void {
    const channel    = vscode.window.createOutputChannel('SLOP Detector');
    const collection = vscode.languages.createDiagnosticCollection('slop-detector');
    const bar        = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Right, 100);

    // A development build says so, so it is never mistaken for an installed release.
    const dev = context.extensionMode === vscode.ExtensionMode.Development;
    bar.text = dev ? '$(beaker) SLOP: Ready (dev build)' : '$(check) SLOP: Ready';
    bar.show();

    initState(collection, bar, channel);
    // Start in the pre-analysis state so viewsWelcome shows Get Started / Analyze.
    void vscode.commands.executeCommand('setContext', 'slop.hasAnalyzed', false);
    channel.appendLine(
        `[*] AI SLOP Detector v${context.extension.packageJSON.version}${dev ? ' (dev build)' : ''} activated`,
    );

    context.subscriptions.push(collection, bar, channel);

    // P3: TreeView sidebar
    const treeProvider = new SlopTreeProvider();
    setTreeRefreshCallback(() => treeProvider.refresh());
    const treeView = vscode.window.createTreeView('slopDetector.fileTree', {
        treeDataProvider: treeProvider,
        showCollapseAll: true,
    });
    context.subscriptions.push(treeView);

    // P4: CodeLens — file summary + per-function issue hints
    const codeLensProvider = new SlopCodeLensProvider();
    setCodeLensRefreshCallback(() => codeLensProvider.refresh());
    context.subscriptions.push(
        vscode.languages.registerCodeLensProvider(
            [{ language: 'python' }, { language: 'javascript' },
             { language: 'typescript' }, { language: 'go' }],
            codeLensProvider,
        )
    );

    // Hover on a flagged line; line highlights with a stronger frame on the
    // line under the cursor or selection.
    context.subscriptions.push(vscode.languages.registerHoverProvider(LANGUAGES, new SlopHoverProvider()));
    const highlighter = new LineHighlighter();
    setHighlightRefreshCallback(() => highlighter.refreshAll());
    context.subscriptions.push(
        highlighter,
        vscode.window.onDidChangeActiveTextEditor((editor) => highlighter.refresh(editor)),
        vscode.window.onDidChangeVisibleTextEditors(() => highlighter.refreshAll()),
        vscode.window.onDidChangeTextEditorSelection((event) => highlighter.refresh(event.textEditor)),
        vscode.workspace.onDidChangeConfiguration((event) => {
            if (event.affectsConfiguration('slopDetector')) { highlighter.refreshAll(); treeProvider.refresh(); }
        }),
    );

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
        ['slop-detector.showOutput',              () => outputChannel.show(true)],
        ['slop-detector.showBreakdown',           showBreakdownPanel],
        ['slop-detector.showCleanupPlan',         showCleanupPanel],
        ['slop-detector.showPulse',               showPulsePanel],
        ['slop-detector.showReview',              showReviewPanel],
        ['slop-detector.addFileToIgnore',         (relPath: string) => addFileToIgnore(relPath)],
        ['slop-detector.addModuleToAllowlist',    (mod: string) => addModuleToAllowlist(mod)],
        // P3: TreeView refresh
        ['slop-detector.refreshTree',        analyzeWorkspace],
        // Reports made by the extension itself
        ['slop-detector.exportReport',       exportReport],
        ['slop-detector.openReport',         openReport],
        ['slop-detector.copyItemForAgent',   (file: string, line: number, rule: string) => copyItemForAgent(file, line, rule)],
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

    // Analyze a file when it is opened or brought to the front, once (until it
    // is saved again): results appear without a save or a command.
    const analyzeOnOpen = (document: vscode.TextDocument | undefined) => {
        if (!document || document.uri.scheme !== 'file' || fileResults.has(document.uri.fsPath)) { return; }
        if (vscode.workspace.getConfiguration('slopDetector').get('analyzeOnOpen', true)) {
            void analyzeDocument(document);
        }
    };
    context.subscriptions.push(
        vscode.window.onDidChangeActiveTextEditor((editor) => analyzeOnOpen(editor?.document)),
    );
    analyzeOnOpen(vscode.window.activeTextEditor?.document);

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
