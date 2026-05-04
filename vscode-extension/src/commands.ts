import * as vscode from 'vscode';
import { exec } from 'child_process';
import { promisify } from 'util';
import * as path from 'path';
import { statusBarItem, outputChannel } from './state';
import { analyzeDocument, extractJson } from './analyzer';

const execAsync = promisify(exec);

export async function analyzeCurrentFile(): Promise<void> {
    const editor = vscode.window.activeTextEditor;
    if (!editor) { vscode.window.showWarningMessage('[!] No active file'); return; }
    await analyzeDocument(editor.document);
}

export async function analyzeWorkspace(): Promise<void> {
    const folders = vscode.workspace.workspaceFolders;
    if (!folders) { vscode.window.showWarningMessage('[!] No workspace folder open'); return; }

    const rootPath   = folders[0].uri.fsPath;
    const config     = vscode.workspace.getConfiguration('slopDetector');
    const pythonPath = config.get('pythonPath', 'python');

    statusBarItem.text = '$(sync~spin) SLOP: Analyzing workspace...';
    try {
        const { stdout } = await execAsync(
            `${pythonPath} -m slop_detector.cli "${rootPath}" --project --json`,
            { maxBuffer: 50 * 1024 * 1024, cwd: rootPath }
        );
        const result = extractJson(stdout);
        const icon = result.overall_status === 'clean' ? '$(check)' : '$(warning)';
        statusBarItem.text = `${icon} SLOP: ${result.avg_deficit_score.toFixed(1)} avg (${result.total_files} files)`;

        const items: vscode.QuickPickItem[] = [];
        items.push({
            label: `$(graph) ${result.overall_status.toUpperCase()} — ${result.total_files} files, avg deficit ${result.avg_deficit_score.toFixed(1)}`,
            kind: vscode.QuickPickItemKind.Separator,
        });

        const deficitFiles = (result.file_results ?? [])
            .filter((f: any) => f.status !== 'clean')
            .sort((a: any, b: any) => b.deficit_score - a.deficit_score);

        for (const f of deficitFiles) {
            const fIcon = f.deficit_score >= 50 ? '$(error)' : '$(warning)';
            items.push({
                label: `${fIcon} ${path.basename(f.file_path)}`,
                description: `${f.deficit_score.toFixed(1)}/100 — ${f.status.toUpperCase()}`,
                detail: `LDR: ${(f.ldr?.ldr_score ?? 0).toFixed(2)}  Inflation: ${(f.inflation?.inflation_score ?? 0).toFixed(2)}  DDC: ${(f.ddc?.usage_ratio ?? 0).toFixed(2)}`,
            });
        }
        if (deficitFiles.length === 0) {
            items.push({ label: '$(check) All files clean', description: 'No issues detected' });
        }

        const selected = await vscode.window.showQuickPick(items, {
            placeHolder: `Workspace: ${result.project_path} — click a file to open`,
            matchOnDescription: true, matchOnDetail: true,
        });
        if (selected && !selected.label.includes('All files') && selected.kind !== vscode.QuickPickItemKind.Separator) {
            const fileName = selected.label.replace(/^\$\([^)]+\)\s*/, '');
            const matched = (result.file_results ?? []).find(
                (f: any) => path.basename(f.file_path) === fileName
            );
            if (matched) {
                const doc = await vscode.workspace.openTextDocument(matched.file_path);
                await vscode.window.showTextDocument(doc);
            }
        }
    } catch (error) {
        vscode.window.showErrorMessage(`[-] Workspace analysis failed: ${error}`);
        statusBarItem.text = '$(error) SLOP: Error';
    }
}

export async function showFileHistory(): Promise<void> {
    const editor = vscode.window.activeTextEditor;
    if (!editor) { vscode.window.showWarningMessage('[!] No active file'); return; }

    const filePath   = editor.document.uri.fsPath;
    const config     = vscode.workspace.getConfiguration('slopDetector');
    const pythonPath = config.get('pythonPath', 'python');

    try {
        const { stdout } = await execAsync(
            `${pythonPath} -m slop_detector.cli "${filePath}" --show-history --json`
        );
        const history = JSON.parse(stdout);
        if (history.length === 0) {
            vscode.window.showInformationMessage('[+] No history found for this file'); return;
        }
        const items = history.map((entry: any) => ({
            label: `${entry.timestamp}`,
            description: `Deficit: ${entry.deficit_score?.toFixed(1) || entry.slop_score?.toFixed(1) || 'N/A'} (${entry.grade || entry.status || 'N/A'})`,
            detail: `LDR: ${entry.ldr_score?.toFixed(3) || 'N/A'}, Inflation: ${entry.inflation_score?.toFixed(3) || 'N/A'}, DDC: ${entry.ddc_usage_ratio?.toFixed(3) || 'N/A'}`,
        }));
        vscode.window.showQuickPick(items, { placeHolder: 'File History' });
    } catch (error) {
        vscode.window.showErrorMessage(`[-] Failed to load history: ${error}`);
    }
}

export async function installGitHook(): Promise<void> {
    const folders = vscode.workspace.workspaceFolders;
    if (!folders) { vscode.window.showWarningMessage('[!] No workspace folder open'); return; }

    const config     = vscode.workspace.getConfiguration('slopDetector');
    const pythonPath = config.get('pythonPath', 'python');
    try {
        await execAsync(`${pythonPath} -m slop_detector.cli --install-git-hook`, {
            cwd: folders[0].uri.fsPath,
        });
        vscode.window.showInformationMessage('[+] Git pre-commit hook installed successfully!');
    } catch (error) {
        vscode.window.showErrorMessage(`[-] Failed to install hook: ${error}`);
    }
}

export async function runCrossFileAnalysis(): Promise<void> {
    const folders = vscode.workspace.workspaceFolders;
    if (!folders) { vscode.window.showWarningMessage('[!] No workspace folder open'); return; }

    const rootPath   = folders[0].uri.fsPath;
    const config     = vscode.workspace.getConfiguration('slopDetector');
    const pythonPath = config.get('pythonPath', 'python');

    statusBarItem.text = '$(sync~spin) SLOP: Cross-file analysis...';
    try {
        const { stdout } = await execAsync(
            `${pythonPath} -m slop_detector.cli "${rootPath}" --project --cross-file`,
            { maxBuffer: 20 * 1024 * 1024, cwd: rootPath }
        );
        outputChannel.appendLine('[Cross-File Analysis]');
        outputChannel.appendLine(stdout);
        outputChannel.show(false);
        vscode.window.showInformationMessage('[+] Cross-file analysis complete — see Output panel');
        statusBarItem.text = '$(check) SLOP: Ready';
    } catch (error) {
        vscode.window.showErrorMessage(`[-] Cross-file analysis failed: ${error}`);
        statusBarItem.text = '$(error) SLOP: Error';
    }
}

export async function showHistoryTrends(): Promise<void> {
    const config     = vscode.workspace.getConfiguration('slopDetector');
    const pythonPath = config.get('pythonPath', 'python');

    statusBarItem.text = '$(sync~spin) SLOP: Loading trends...';
    try {
        const { stdout } = await execAsync(
            `${pythonPath} -m slop_detector.cli --history-trends --json`,
            { maxBuffer: 5 * 1024 * 1024 }
        );
        const trends = extractJson(stdout);
        const files: any[] = Array.isArray(trends)
            ? trends : trends.files ?? Object.values(trends);

        outputChannel.appendLine('');
        outputChannel.appendLine('=== SLOP Detector — History Trends ===');
        outputChannel.appendLine('');

        if (files.length === 0) {
            outputChannel.appendLine('  No history data. Run analysis on files to build history.');
        } else {
            const colW   = 40;
            const header = `${'File'.padEnd(colW)}  ${'Runs'.padStart(4)}  ${'Latest'.padStart(7)}  ${'Best'.padStart(7)}  ${'Worst'.padStart(7)}  Trend`;
            outputChannel.appendLine(header);
            outputChannel.appendLine('-'.repeat(header.length));
            for (const entry of files) {
                const name    = path.basename(entry.file_path ?? entry.path ?? 'unknown').padEnd(colW).slice(0, colW);
                const runs    = String(entry.run_count ?? entry.total_runs ?? '?').padStart(4);
                const latest  = (entry.latest_deficit ?? entry.last_score ?? 0).toFixed(1).padStart(7);
                const best    = (entry.best_deficit   ?? entry.min_score  ?? 0).toFixed(1).padStart(7);
                const worst   = (entry.worst_deficit  ?? entry.max_score  ?? 0).toFixed(1).padStart(7);
                const latestN = parseFloat(latest);
                const prevN   = entry.previous_deficit ?? entry.prev_score ?? latestN;
                const trend   = latestN < prevN - 1 ? 'improving' : latestN > prevN + 1 ? 'degrading' : 'stable';
                outputChannel.appendLine(`${name}  ${runs}  ${latest}  ${best}  ${worst}  ${trend}`);
            }
        }
        outputChannel.appendLine('');
        outputChannel.show(false);
        vscode.window.showInformationMessage(`[+] History Trends — ${files.length} file(s). See Output panel.`);
        statusBarItem.text = '$(check) SLOP: Ready';
    } catch (error) {
        const msg = error instanceof Error ? error.message : String(error);
        vscode.window.showErrorMessage(`[-] History Trends failed: ${msg}`);
        statusBarItem.text = '$(error) SLOP: Error';
    }
}

export async function exportHistory(): Promise<void> {
    const saveUri = await vscode.window.showSaveDialog({
        defaultUri: vscode.Uri.file('slop_history.jsonl'),
        filters: { 'JSONL': ['jsonl'], 'All Files': ['*'] },
        saveLabel: 'Export History',
    });
    if (!saveUri) { return; }

    const config     = vscode.workspace.getConfiguration('slopDetector');
    const pythonPath = config.get('pythonPath', 'python');

    statusBarItem.text = '$(sync~spin) SLOP: Exporting...';
    try {
        await execAsync(
            `${pythonPath} -m slop_detector.cli --export-history "${saveUri.fsPath}"`,
            { maxBuffer: 50 * 1024 * 1024 }
        );
        vscode.window.showInformationMessage(`[+] History exported to ${saveUri.fsPath}`);
        statusBarItem.text = '$(check) SLOP: Ready';
    } catch (error) {
        const msg = error instanceof Error ? error.message : String(error);
        vscode.window.showErrorMessage(`[-] Export History failed: ${msg}`);
        statusBarItem.text = '$(error) SLOP: Error';
    }
}
