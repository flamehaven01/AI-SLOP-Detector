import * as vscode from 'vscode';
import { exec } from 'child_process';
import { promisify } from 'util';
import * as path from 'path';

const execAsync = promisify(exec);

let diagnosticCollection: vscode.DiagnosticCollection;
let statusBarItem: vscode.StatusBarItem;
let outputChannel: vscode.OutputChannel;

export function activate(context: vscode.ExtensionContext) {
    outputChannel = vscode.window.createOutputChannel('SLOP Detector');
    context.subscriptions.push(outputChannel);

    outputChannel.appendLine('[*] AI SLOP Detector extension activated');

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

    outputChannel.appendLine(`[*] Analyzing: ${filePath}`);
    statusBarItem.text = "$(sync~spin) SLOP: Analyzing...";

    try {
        const result = await runSlopDetector(filePath, config);
        updateDiagnostics(document.uri, result);
        updateStatusBar(result);
        outputChannel.appendLine(`[+] Analysis complete: Deficit=${result.deficit_score}, Status=${result.status}`);
    } catch (error) {
        const errorMsg = error instanceof Error ? error.message : String(error);
        outputChannel.appendLine(`[!] Analysis failed: ${errorMsg}`);
        outputChannel.show(true);
        vscode.window.showErrorMessage(`SLOP Detector failed: ${errorMsg}`);
        statusBarItem.text = "$(error) SLOP: Error";
    }
}

async function runSlopDetector(filePath: string, config: vscode.WorkspaceConfiguration): Promise<any> {
    const pythonPath = config.get('pythonPath', 'python');
    const configPath = config.get('configPath', '');

    let command = `${pythonPath} -m slop_detector.cli "${filePath}" --json`;

    if (configPath) {
        command += ` --config "${configPath}"`;
    }

    outputChannel.appendLine(`[*] Running command: ${command}`);

    const { stdout, stderr } = await execAsync(command, { maxBuffer: 10 * 1024 * 1024 });

    if (stderr) {
        outputChannel.appendLine(`[!] stderr: ${stderr}`);
    }

    outputChannel.appendLine(`[*] stdout length: ${stdout.length} bytes`);

    return JSON.parse(stdout);
}

function updateDiagnostics(uri: vscode.Uri, result: any) {
    const diagnostics: vscode.Diagnostic[] = [];
    const config = vscode.workspace.getConfiguration('slopDetector');
    const failThreshold = config.get('failThreshold', 50.0);
    const warnThreshold = config.get('warnThreshold', 30.0);

    const deficitScore = result.deficit_score || 0;

    let overallSeverity = vscode.DiagnosticSeverity.Information;
    if (deficitScore >= failThreshold) {
        overallSeverity = vscode.DiagnosticSeverity.Error;
    } else if (deficitScore >= warnThreshold) {
        overallSeverity = vscode.DiagnosticSeverity.Warning;
    }

    // Overall summary diagnostic
    const summaryMessage = `Code Quality Summary (Score: ${deficitScore.toFixed(1)})\n` +
                          `Status: ${result.status}\n` +
                          `LDR: ${result.ldr.ldr_score.toFixed(3)}, ` +
                          `Inflation: ${result.inflation.inflation_score.toFixed(3)}, ` +
                          `DDC: ${result.ddc.usage_ratio.toFixed(3)}`;

    const summaryDiagnostic = new vscode.Diagnostic(
        new vscode.Range(0, 0, 0, 0),
        summaryMessage,
        overallSeverity
    );
    summaryDiagnostic.source = 'SLOP Detector';
    diagnostics.push(summaryDiagnostic);

    // Add jargon-specific diagnostics
    if (result.inflation && result.inflation.jargon_details) {
        for (const jargon of result.inflation.jargon_details) {
            const line = Math.max(0, (jargon.line || 1) - 1);
            const message = `Unjustified jargon: "${jargon.word}" (${jargon.category})`;

            const diagnostic = new vscode.Diagnostic(
                new vscode.Range(line, 0, line, 1000),
                message,
                vscode.DiagnosticSeverity.Warning
            );
            diagnostic.source = 'SLOP Detector - Inflation';
            diagnostic.code = 'jargon';
            diagnostics.push(diagnostic);
        }
    }

    // Add unused import diagnostics
    if (result.ddc && result.ddc.unused && result.ddc.unused.length > 0) {
        const unusedImports = result.ddc.unused;
        const message = `Unused imports detected: ${unusedImports.join(', ')}`;

        const diagnostic = new vscode.Diagnostic(
            new vscode.Range(0, 0, 0, 1000),
            message,
            vscode.DiagnosticSeverity.Information
        );
        diagnostic.source = 'SLOP Detector - DDC';
        diagnostic.code = 'unused-import';
        diagnostics.push(diagnostic);
    }

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
    const deficitScore = result.deficit_score || 0;
    const status = result.status || 'unknown';

    let icon = '$(check)';
    let severityLabel = 'Good';
    if (deficitScore >= 50) {
        icon = '$(error)';
        severityLabel = 'Error';
    } else if (deficitScore >= 30) {
        icon = '$(warning)';
        severityLabel = 'Warning';
    }

    // Show severity level first, score in parentheses
    statusBarItem.text = `${icon} ${severityLabel} (${deficitScore.toFixed(1)})`;
    statusBarItem.tooltip = `Code Quality: ${severityLabel}\n` +
                           `Deficit Score: ${deficitScore.toFixed(1)}\n` +
                           `Status: ${status}\n\n` +
                           `Metrics:\n` +
                           `• LDR: ${result.ldr.ldr_score.toFixed(3)}\n` +
                           `• Inflation: ${result.inflation.inflation_score.toFixed(3)}\n` +
                           `• DDC: ${result.ddc.usage_ratio.toFixed(3)}`;
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
            `Avg Deficit: ${result.avg_deficit_score.toFixed(1)}\n` +
            `Status: ${result.overall_status}`
        );

        statusBarItem.text = `$(check) SLOP: ${result.avg_deficit_score.toFixed(1)} (Workspace)`;
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
