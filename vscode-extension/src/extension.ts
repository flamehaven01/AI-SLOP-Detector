import * as vscode from 'vscode';
import { exec } from 'child_process';
import { promisify } from 'util';
import * as path from 'path';

const execAsync = promisify(exec);

let diagnosticCollection: vscode.DiagnosticCollection;
let statusBarItem: vscode.StatusBarItem;

export function activate(context: vscode.ExtensionContext) {
    console.log('[*] AI SLOP Detector extension activated');

    diagnosticCollection = vscode.languages.createDiagnosticCollection('slop-detector');
    context.subscriptions.push(diagnosticCollection);

    // Status bar item
    statusBarItem = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Right, 100);
    statusBarItem.text = "$(check) SLOP: Ready";
    statusBarItem.show();
    context.subscriptions.push(statusBarItem);

    // Commands
    context.subscriptions.push(
        vscode.commands.registerCommand('slop-detector.analyzeFile', analyzeCurrentFile)
    );
    context.subscriptions.push(
        vscode.commands.registerCommand('slop-detector.analyzeWorkspace', analyzeWorkspace)
    );
    context.subscriptions.push(
        vscode.commands.registerCommand('slop-detector.showHistory', showFileHistory)
    );
    context.subscriptions.push(
        vscode.commands.registerCommand('slop-detector.installGitHook', installGitHook)
    );

    // Auto-lint on save
    context.subscriptions.push(
        vscode.workspace.onDidSaveTextDocument(document => {
            const config = vscode.workspace.getConfiguration('slopDetector');
            if (config.get('lintOnSave')) {
                analyzeDocument(document);
            }
        })
    );

    // Auto-lint on type (if enabled)
    context.subscriptions.push(
        vscode.workspace.onDidChangeTextDocument(event => {
            const config = vscode.workspace.getConfiguration('slopDetector');
            if (config.get('lintOnType')) {
                analyzeDocument(event.document);
            }
        })
    );
}

async function analyzeCurrentFile() {
    const editor = vscode.window.activeTextEditor;
    if (!editor) {
        vscode.window.showWarningMessage('[!] No active file');
        return;
    }
    
    await analyzeDocument(editor.document);
}

async function analyzeDocument(document: vscode.TextDocument) {
    const config = vscode.workspace.getConfiguration('slopDetector');
    
    if (!config.get('enable')) {
        return;
    }

    const filePath = document.uri.fsPath;
    const supportedExtensions = ['.py', '.js', '.ts'];
    
    if (!supportedExtensions.some(ext => filePath.endsWith(ext))) {
        return;
    }

    statusBarItem.text = "$(sync~spin) SLOP: Analyzing...";

    try {
        const result = await runSlopDetector(filePath, config);
        updateDiagnostics(document.uri, result);
        updateStatusBar(result);
    } catch (error) {
        console.error('[!] Analysis failed:', error);
        statusBarItem.text = "$(error) SLOP: Error";
    }
}

async function runSlopDetector(filePath: string, config: vscode.WorkspaceConfiguration): Promise<any> {
    const pythonPath = config.get('pythonPath', 'python');
    const configPath = config.get('configPath', '');
    const recordHistory = config.get('recordHistory', true);

    let command = `${pythonPath} -m slop_detector.cli "${filePath}" --json`;
    
    if (configPath) {
        command += ` --config "${configPath}"`;
    }
    
    if (recordHistory) {
        command += ' --record-history';
    }

    const { stdout, stderr } = await execAsync(command, { maxBuffer: 10 * 1024 * 1024 });
    
    if (stderr) {
        console.warn('[!] stderr:', stderr);
    }

    return JSON.parse(stdout);
}

function updateDiagnostics(uri: vscode.Uri, result: any) {
    const diagnostics: vscode.Diagnostic[] = [];
    const config = vscode.workspace.getConfiguration('slopDetector');
    const failThreshold = config.get('failThreshold', 50.0);
    const warnThreshold = config.get('warnThreshold', 30.0);

    const slopScore = result.slop_score;
    
    let severity = vscode.DiagnosticSeverity.Information;
    if (slopScore >= failThreshold) {
        severity = vscode.DiagnosticSeverity.Error;
    } else if (slopScore >= warnThreshold) {
        severity = vscode.DiagnosticSeverity.Warning;
    }

    const message = `SLOP Score: ${slopScore.toFixed(1)} (${result.grade})\n` +
                   `LDR: ${result.ldr.ldr_score.toFixed(3)}, ` +
                   `BCR: ${result.bcr.bcr_score.toFixed(3)}, ` +
                   `DDC: ${result.ddc.usage_ratio.toFixed(3)}`;

    const diagnostic = new vscode.Diagnostic(
        new vscode.Range(0, 0, 0, 0),
        message,
        severity
    );
    diagnostic.source = 'SLOP Detector';

    diagnostics.push(diagnostic);

    // Add pattern-specific diagnostics
    if (result.patterns) {
        for (const pattern of result.patterns) {
            if (pattern.severity === 'critical' || pattern.severity === 'high') {
                const patternDiag = new vscode.Diagnostic(
                    new vscode.Range(0, 0, 0, 0),
                    `[${pattern.category}] ${pattern.message}`,
                    pattern.severity === 'critical' 
                        ? vscode.DiagnosticSeverity.Error 
                        : vscode.DiagnosticSeverity.Warning
                );
                patternDiag.source = 'SLOP Detector - Patterns';
                diagnostics.push(patternDiag);
            }
        }
    }

    diagnosticCollection.set(uri, diagnostics);
}

function updateStatusBar(result: any) {
    const slopScore = result.slop_score;
    const grade = result.grade;

    let icon = '$(check)';
    if (slopScore >= 50) {
        icon = '$(error)';
    } else if (slopScore >= 30) {
        icon = '$(warning)';
    }

    statusBarItem.text = `${icon} SLOP: ${slopScore.toFixed(1)} (${grade})`;
    statusBarItem.tooltip = `LDR: ${result.ldr.ldr_score.toFixed(3)}\n` +
                           `BCR: ${result.bcr.bcr_score.toFixed(3)}\n` +
                           `DDC: ${result.ddc.usage_ratio.toFixed(3)}`;
}

async function analyzeWorkspace() {
    const workspaceFolders = vscode.workspace.workspaceFolders;
    if (!workspaceFolders) {
        vscode.window.showWarningMessage('[!] No workspace folder open');
        return;
    }

    const rootPath = workspaceFolders[0].uri.fsPath;
    const config = vscode.workspace.getConfiguration('slopDetector');
    const pythonPath = config.get('pythonPath', 'python');

    statusBarItem.text = "$(sync~spin) SLOP: Analyzing workspace...";

    try {
        const command = `${pythonPath} -m slop_detector.cli "${rootPath}" --project --json`;
        const { stdout } = await execAsync(command, { 
            maxBuffer: 50 * 1024 * 1024,
            cwd: rootPath 
        });

        const result = JSON.parse(stdout);

        vscode.window.showInformationMessage(
            `[+] Workspace Analysis Complete\n` +
            `Files: ${result.total_files}\n` +
            `Avg Slop: ${result.avg_slop_score.toFixed(1)}\n` +
            `Grade: ${result.overall_grade}`
        );

        statusBarItem.text = `$(check) SLOP: ${result.avg_slop_score.toFixed(1)} (Workspace)`;
    } catch (error) {
        vscode.window.showErrorMessage(`[-] Workspace analysis failed: ${error}`);
        statusBarItem.text = "$(error) SLOP: Error";
    }
}

async function showFileHistory() {
    const editor = vscode.window.activeTextEditor;
    if (!editor) {
        vscode.window.showWarningMessage('[!] No active file');
        return;
    }

    const filePath = editor.document.uri.fsPath;
    const config = vscode.workspace.getConfiguration('slopDetector');
    const pythonPath = config.get('pythonPath', 'python');

    try {
        const command = `${pythonPath} -m slop_detector.cli "${filePath}" --show-history --json`;
        const { stdout } = await execAsync(command);

        const history = JSON.parse(stdout);

        if (history.length === 0) {
            vscode.window.showInformationMessage('[+] No history found for this file');
            return;
        }

        const items = history.map((entry: any) => ({
            label: `${entry.timestamp}`,
            description: `Score: ${entry.slop_score.toFixed(1)} (${entry.grade})`,
            detail: `LDR: ${entry.ldr_score.toFixed(3)}, BCR: ${entry.bcr_score.toFixed(3)}, DDC: ${entry.ddc_usage_ratio.toFixed(3)}`
        }));

        vscode.window.showQuickPick(items, {
            placeHolder: 'File History'
        });

    } catch (error) {
        vscode.window.showErrorMessage(`[-] Failed to load history: ${error}`);
    }
}

async function installGitHook() {
    const workspaceFolders = vscode.workspace.workspaceFolders;
    if (!workspaceFolders) {
        vscode.window.showWarningMessage('[!] No workspace folder open');
        return;
    }

    const rootPath = workspaceFolders[0].uri.fsPath;
    const config = vscode.workspace.getConfiguration('slopDetector');
    const pythonPath = config.get('pythonPath', 'python');

    try {
        const command = `${pythonPath} -m slop_detector.cli --install-git-hook`;
        await execAsync(command, { cwd: rootPath });

        vscode.window.showInformationMessage('[+] Git pre-commit hook installed successfully!');
    } catch (error) {
        vscode.window.showErrorMessage(`[-] Failed to install hook: ${error}`);
    }
}

export function deactivate() {
    if (diagnosticCollection) {
        diagnosticCollection.dispose();
    }
    if (statusBarItem) {
        statusBarItem.dispose();
    }
}
