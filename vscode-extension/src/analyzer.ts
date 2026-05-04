import * as vscode from 'vscode';
import { exec } from 'child_process';
import { promisify } from 'util';
import { statusBarItem, outputChannel, updateFileResult } from './state';
import { updateDiagnostics } from './diagnostics';
import { updateStatusBar } from './statusbar';
import { parseSlopReport, ISlopReport } from './schema';

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
): Promise<ISlopReport> {
    const pythonPath    = config.get('pythonPath', 'python');
    const configPath    = config.get('configPath', '');
    const recordHistory = config.get('recordHistory', true);

    let command = `${pythonPath} -m slop_detector.cli "${filePath}" --json`;
    if (configPath)      { command += ` --config "${configPath}"`; }
    if (!recordHistory)  { command += ' --no-history'; }

    outputChannel.appendLine(`[*] Running: ${command}`);
    const { stdout, stderr } = await execAsync(command, { maxBuffer: 10 * 1024 * 1024 });
    if (stderr) { outputChannel.appendLine(`[!] stderr: ${stderr}`); }

    const raw    = extractJson(stdout);
    const parsed = parseSlopReport(raw);
    if (!parsed.ok) {
        const { field, expected, got } = parsed.error;
        throw new Error(
            `CLI output schema mismatch — "${field}": expected ${expected}, got ${got}. ` +
            `Check that slop-detector is installed and up to date.`
        );
    }
    return parsed.value;
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
        updateFileResult(filePath, result);
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
