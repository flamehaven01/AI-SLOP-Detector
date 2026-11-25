import * as vscode from 'vscode';
import * as path from 'path';
import { statusBarItem, outputChannel } from './state';
import { analyzeDocument } from './analyzer';
import * as client from './client';
import { parseGateDecision } from './backendText';

export async function autoFixCurrentFile(): Promise<void> {
    const editor = vscode.window.activeTextEditor;
    if (!editor) { vscode.window.showWarningMessage('[!] No active file'); return; }

    const filePath = editor.document.uri.fsPath;
    if (!filePath.endsWith('.py')) {
        vscode.window.showWarningMessage('[!] Auto-fix is supported for Python files only');
        return;
    }

    const choice = await vscode.window.showInformationMessage(
        'Auto-Fix: Apply fixes to detected slop patterns?',
        'Preview (dry-run)', 'Apply Fixes', 'Cancel'
    );
    if (!choice || choice === 'Cancel') { return; }

    const args = [filePath, '--fix'];
    if (choice === 'Preview (dry-run)') { args.push('--dry-run'); }

    outputChannel.appendLine(`[*] Auto-Fix: ${filePath} --fix`);
    statusBarItem.text = '$(sync~spin) SLOP: Fixing...';
    try {
        const { stdout, stderr } = await client.runText(args, path.dirname(filePath));
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

    const filePath = editor.document.uri.fsPath;

    // The decision is a text block after the analysis JSON; there is no JSON
    // field for it. A non-zero exit can still carry the block, so it is read
    // from the output either way; without a readable block nothing is assumed.
    let stdout = '';
    let failure = '';
    try {
        ({ stdout } = await client.runText([filePath, '--gate', '--json'], path.dirname(filePath)));
    } catch (error: any) {
        stdout = String(error?.stdout ?? '');
        failure = error instanceof Error ? error.message : String(error);
    }
    const gate = parseGateDecision(stdout);
    if (!gate) {
        outputChannel.appendLine(failure || stdout);
        outputChannel.show(false);
        vscode.window.showWarningMessage(
            '[!] Gate decision UNVERIFIED: the backend gave no readable decision. See Output panel.');
        return;
    }
    outputChannel.appendLine(gate.block);
    const msg = `Gate [${gate.status}]: ${gate.metrics}`;
    gate.allowed
        ? vscode.window.showInformationMessage(msg)
        : vscode.window.showWarningMessage(`${msg}\n${gate.halt ?? ''}`);
}

export async function initConfig(): Promise<void> {
    const folders = vscode.workspace.workspaceFolders;
    if (!folders) { vscode.window.showWarningMessage('[!] No workspace folder open'); return; }

    const rootPath = folders[0].uri.fsPath;
    const config   = vscode.workspace.getConfiguration('slopDetector');

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
        const args = ['--init', rootPath];
        if (existing.length > 0) { args.push('--force-init'); }
        const domain = config.get<string>('domain', 'auto');
        if (domain && domain !== 'auto') { args.push('--domain', domain); }
        const { stdout, stderr } = await client.runText(args, rootPath);
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

    statusBarItem.text = '$(sync~spin) SLOP: Calibrating...';
    try {
        // Advisory only: the legacy history is not provenance-stable, so the CLI never
        // writes weights (--apply-calibration exits 2). Exit 1 means insufficient data,
        // which is a report, not a failure.
        let stdout: string;
        let stderr: string;
        try {
            ({ stdout, stderr } = await client.runText(['--self-calibrate'], rootPath));
        } catch (error) {
            const failed = error as { code?: number; stdout?: string; stderr?: string };
            if (failed.code !== 1 || !failed.stdout) { throw error; }
            stdout = failed.stdout;
            stderr = failed.stderr ?? '';
        }
        outputChannel.clear();
        outputChannel.appendLine('=== SLOP Detector: Self-Calibration (advisory) ===');
        outputChannel.appendLine(stdout);
        if (stderr) { outputChannel.appendLine(stderr); }
        outputChannel.show(true);

        if (stdout.includes('insufficient_data') || stdout.includes('INSUFFICIENT_DATA')) {
            vscode.window.showWarningMessage(
                '[!] Not enough history yet for an advisory calibration report.'
            );
        } else {
            vscode.window.showInformationMessage(
                '[=] Advisory report only: weights are not applied until Calibration v2. '
                + 'Edit .slopconfig.yaml yourself to change them.'
            );
        }
        statusBarItem.text = '$(check) SLOP: Ready';
    } catch (error) {
        const msg = error instanceof Error ? error.message : String(error);
        vscode.window.showErrorMessage(`[-] Self-calibration failed: ${msg}`);
        statusBarItem.text = '$(error) SLOP: Error';
    }
}
