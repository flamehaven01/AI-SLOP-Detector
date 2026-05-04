import * as vscode from 'vscode';
import { exec } from 'child_process';
import { promisify } from 'util';
import { statusBarItem, outputChannel } from './state';
import { analyzeDocument } from './analyzer';

const execAsync = promisify(exec);

export async function autoFixCurrentFile(): Promise<void> {
    const editor = vscode.window.activeTextEditor;
    if (!editor) { vscode.window.showWarningMessage('[!] No active file'); return; }

    const filePath = editor.document.uri.fsPath;
    if (!filePath.endsWith('.py')) {
        vscode.window.showWarningMessage('[!] Auto-fix is supported for Python files only');
        return;
    }

    const config     = vscode.workspace.getConfiguration('slopDetector');
    const pythonPath = config.get('pythonPath', 'python');
    const choice     = await vscode.window.showInformationMessage(
        'Auto-Fix: Apply fixes to detected slop patterns?',
        'Preview (dry-run)', 'Apply Fixes', 'Cancel'
    );
    if (!choice || choice === 'Cancel') { return; }

    const dryRunFlag = choice === 'Preview (dry-run)' ? '--dry-run' : '';
    const command    = `${pythonPath} -m slop_detector.cli "${filePath}" --fix ${dryRunFlag}`.trim();

    outputChannel.appendLine(`[*] Auto-Fix: ${command}`);
    statusBarItem.text = '$(sync~spin) SLOP: Fixing...';
    try {
        const { stdout, stderr } = await execAsync(command, { maxBuffer: 10 * 1024 * 1024 });
        outputChannel.appendLine(stdout);
        if (stderr) { outputChannel.appendLine(stderr); }
        const label = choice === 'Preview (dry-run)' ? 'Preview complete' : 'Fixes applied';
        vscode.window.showInformationMessage(`[+] ${label} — see Output panel`);
        outputChannel.show(false);
        if (choice !== 'Preview (dry-run)') { await analyzeDocument(editor.document); }
    } catch (error) {
        const msg = error instanceof Error ? error.message : String(error);
        vscode.window.showErrorMessage(`[-] Auto-Fix failed: ${msg}`);
        statusBarItem.text = '$(error) SLOP: Error';
    }
}

export async function showGateDecision(): Promise<void> {
    const editor = vscode.window.activeTextEditor;
    if (!editor) { vscode.window.showWarningMessage('[!] No active file'); return; }

    const filePath   = editor.document.uri.fsPath;
    const config     = vscode.workspace.getConfiguration('slopDetector');
    const pythonPath = config.get('pythonPath', 'python');

    try {
        const { stdout } = await execAsync(
            `${pythonPath} -m slop_detector.cli "${filePath}" --gate --json`,
            { maxBuffer: 5 * 1024 * 1024 }
        );
        const result = JSON.parse(stdout);
        const gate   = result.gate_decision;
        if (gate) {
            const status = gate.allowed ? '[PASS]' : '[HALT]';
            const msg    =
                `Gate ${status}: sr9=${gate.metrics_snapshot.sr9?.toFixed(3)} ` +
                `di2=${gate.metrics_snapshot.di2?.toFixed(3)} ` +
                `jsd=${gate.metrics_snapshot.jsd?.toFixed(3)} ` +
                `ove=${gate.metrics_snapshot.ove?.toFixed(3)}`;
            gate.allowed
                ? vscode.window.showInformationMessage(msg)
                : vscode.window.showWarningMessage(`${msg}\n${gate.halt_reason || ''}`);
        } else {
            outputChannel.appendLine(stdout);
            outputChannel.show(false);
        }
    } catch (error) {
        vscode.window.showErrorMessage(`[-] Gate check failed: ${error}`);
    }
}

export async function initConfig(): Promise<void> {
    const folders = vscode.workspace.workspaceFolders;
    if (!folders) { vscode.window.showWarningMessage('[!] No workspace folder open'); return; }

    const rootPath   = folders[0].uri.fsPath;
    const config     = vscode.workspace.getConfiguration('slopDetector');
    const pythonPath = config.get('pythonPath', 'python');

    const existing = await vscode.workspace.findFiles(
        new vscode.RelativePattern(folders[0], '.slopconfig.yaml'), undefined, 1
    );
    if (existing.length > 0) {
        const choice = await vscode.window.showWarningMessage(
            '.slopconfig.yaml already exists. Overwrite?', 'Overwrite', 'Cancel'
        );
        if (choice !== 'Overwrite') { return; }
    }

    statusBarItem.text = '$(sync~spin) SLOP: Initializing config...';
    try {
        const forceFlag = existing.length > 0 ? ' --force-init' : '';
        const { stdout, stderr } = await execAsync(
            `${pythonPath} -m slop_detector.cli --init "${rootPath}"${forceFlag}`,
            { maxBuffer: 10 * 1024 * 1024, cwd: rootPath }
        );
        outputChannel.clear();
        outputChannel.appendLine('=== SLOP Detector: Init Config ===');
        outputChannel.appendLine(stdout);
        if (stderr) { outputChannel.appendLine(stderr); }
        outputChannel.show(true);
        vscode.window.showInformationMessage('[+] .slopconfig.yaml created. See Output for details.');
        statusBarItem.text = '$(check) SLOP: Ready';
    } catch (error) {
        const msg = error instanceof Error ? error.message : String(error);
        vscode.window.showErrorMessage(`[-] Init config failed: ${msg}`);
        statusBarItem.text = '$(error) SLOP: Error';
    }
}

export async function selfCalibrate(): Promise<void> {
    const folders    = vscode.workspace.workspaceFolders;
    const rootPath   = folders?.[0]?.uri.fsPath ?? '.';
    const config     = vscode.workspace.getConfiguration('slopDetector');
    const pythonPath = config.get('pythonPath', 'python');

    statusBarItem.text = '$(sync~spin) SLOP: Calibrating...';
    try {
        const { stdout, stderr } = await execAsync(
            `${pythonPath} -m slop_detector.cli --self-calibrate`,
            { maxBuffer: 10 * 1024 * 1024, cwd: rootPath }
        );
        outputChannel.clear();
        outputChannel.appendLine('=== SLOP Detector: Self-Calibration (LEDA) ===');
        outputChannel.appendLine(stdout);
        if (stderr) { outputChannel.appendLine(stderr); }
        outputChannel.show(true);

        if (stdout.includes('insufficient_data') || stdout.includes('Not enough')) {
            vscode.window.showWarningMessage(
                '[!] Not enough history yet. Run more analyses to build the calibration dataset.'
            );
        } else if (stdout.includes('no_change') || stdout.includes('No change')) {
            vscode.window.showInformationMessage('[=] Calibration: current weights are already optimal.');
        } else {
            const choice = await vscode.window.showInformationMessage(
                '[*] Calibration ready. Apply new weights to .slopconfig.yaml?',
                'Apply', 'View Only'
            );
            if (choice === 'Apply') {
                const { stdout: applyOut } = await execAsync(
                    `${pythonPath} -m slop_detector.cli --self-calibrate --apply-calibration`,
                    { maxBuffer: 10 * 1024 * 1024, cwd: rootPath }
                );
                outputChannel.appendLine('\n--- Apply Calibration ---');
                outputChannel.appendLine(applyOut);
                vscode.window.showInformationMessage('[+] Weights applied to .slopconfig.yaml');
            }
        }
        statusBarItem.text = '$(check) SLOP: Ready';
    } catch (error) {
        const msg = error instanceof Error ? error.message : String(error);
        vscode.window.showErrorMessage(`[-] Self-calibration failed: ${msg}`);
        statusBarItem.text = '$(error) SLOP: Error';
    }
}
