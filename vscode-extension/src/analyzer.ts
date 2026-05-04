import * as vscode from 'vscode';
import { exec } from 'child_process';
import { promisify } from 'util';
import { statusBarItem, outputChannel } from './state';
import { updateDiagnostics } from './diagnostics';
import { updateStatusBar } from './statusbar';

const execAsync = promisify(exec);

/** Extract first JSON object/array from stdout, ignoring leading [INFO] log lines. */
export function extractJson(stdout: string): any {
    const idx = stdout.search(/^\s*[{[]/m);
    if (idx >= 0) { return JSON.parse(stdout.slice(idx)); }
    return JSON.parse(stdout);
}

export async function runSlopDetector(
    filePath: string,
    config: vscode.WorkspaceConfiguration,
): Promise<any> {
    const pythonPath    = config.get('pythonPath', 'python');
    const configPath    = config.get('configPath', '');
    const recordHistory = config.get('recordHistory', true);

    let command = `${pythonPath} -m slop_detector.cli "${filePath}" --json`;
    if (configPath)      { command += ` --config "${configPath}"`; }
    if (!recordHistory)  { command += ' --no-history'; }

    outputChannel.appendLine(`[*] Running: ${command}`);
    const { stdout, stderr } = await execAsync(command, { maxBuffer: 10 * 1024 * 1024 });
    if (stderr) { outputChannel.appendLine(`[!] stderr: ${stderr}`); }
    return extractJson(stdout);
}

export async function analyzeDocument(document: vscode.TextDocument): Promise<void> {
    const config = vscode.workspace.getConfiguration('slopDetector');
    if (!config.get('enable')) { return; }

    const filePath = document.uri.fsPath;
    const supported = ['.py', '.js', '.ts', '.go'];
    if (!supported.some(ext => filePath.endsWith(ext))) { return; }

    outputChannel.appendLine(`[*] Analyzing: ${filePath}`);
    statusBarItem.text = '$(sync~spin) SLOP: Analyzing...';

    try {
        const result = await runSlopDetector(filePath, config);
        updateDiagnostics(document.uri, result);
        updateStatusBar(result);
        outputChannel.appendLine(
            `[+] Analysis complete: Deficit=${result.deficit_score}, Status=${result.status}`
        );
    } catch (error) {
        const msg = error instanceof Error ? error.message : String(error);
        outputChannel.appendLine(`[!] Analysis failed: ${msg}`);
        outputChannel.show(true);
        vscode.window.showErrorMessage(`SLOP Detector failed: ${msg}`);
        statusBarItem.text = '$(error) SLOP: Error';
    }
}
