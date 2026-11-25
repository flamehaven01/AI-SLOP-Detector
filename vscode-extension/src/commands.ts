import * as vscode from 'vscode';
import * as path from 'path';
import { statusBarItem, outputChannel, replaceFileResults } from './state';
import { analyzeDocument } from './analyzer';
import * as client from './client';
import { projectFileResults } from './findings';
import { isInside } from './backendText';

interface ResultQuickPickItem extends vscode.QuickPickItem {
    filePath?: string;
}

export async function analyzeCurrentFile(): Promise<void> {
    const editor = vscode.window.activeTextEditor;
    if (!editor) { vscode.window.showWarningMessage('[!] No active file'); return; }
    await analyzeDocument(editor.document);
}

export async function analyzeWorkspace(): Promise<void> {
    const folders = vscode.workspace.workspaceFolders;
    if (!folders) { vscode.window.showWarningMessage('[!] No workspace folder open'); return; }

    const rootPath   = folders[0].uri.fsPath;

    statusBarItem.text = '$(sync~spin) SLOP: Analyzing workspace...';
    try {
        const result = await client.scanProject(rootPath);
        const files = projectFileResults(result, rootPath);
        replaceFileResults(files);
        const icon = result.overall_status === 'clean' ? '$(check)' : '$(warning)';
        statusBarItem.text = `${icon} SLOP: ${result.avg_deficit_score.toFixed(1)} avg (${result.total_files} files)`;

        const items: ResultQuickPickItem[] = [];
        items.push({
            label: `$(graph) ${result.overall_status.toUpperCase()} — ${result.total_files} files, avg deficit ${result.avg_deficit_score.toFixed(1)}`,
            kind: vscode.QuickPickItemKind.Separator,
        });

        const deficitFiles = files
            .filter((f: any) => f.status !== 'clean')
            .sort((a: any, b: any) => b.deficit_score - a.deficit_score);

        for (const f of deficitFiles) {
            const fIcon = f.deficit_score >= 50 ? '$(error)' : '$(warning)';
            items.push({
                label: `${fIcon} ${path.basename(f.file_path)}`,
                description: `${f.deficit_score.toFixed(1)}/100 — ${f.status.toUpperCase()}`,
                detail: f.language
                    ? `${f.language}: LDR-equivalent ${(f.ldr?.ldr_score ?? 0).toFixed(2)}`
                    : `LDR: ${(f.ldr?.ldr_score ?? 0).toFixed(2)}  Inflation: ${(f.inflation?.inflation_score ?? 0).toFixed(2)}  DDC: ${(f.ddc?.usage_ratio ?? 0).toFixed(2)}`,
                filePath: f.file_path,
            });
        }
        if (deficitFiles.length === 0) {
            items.push({ label: '$(check) All files clean', description: 'No issues detected' });
        }

        const selected = await vscode.window.showQuickPick(items, {
            placeHolder: `Workspace: ${result.project_path} — click a file to open`,
            matchOnDescription: true, matchOnDetail: true,
        });
        if (selected?.filePath) {
            const doc = await vscode.workspace.openTextDocument(selected.filePath);
            await vscode.window.showTextDocument(doc);
        }
    } catch (error) {
        vscode.window.showErrorMessage(`[-] Workspace analysis failed: ${error}`);
        statusBarItem.text = '$(error) SLOP: Error';
    }
}

export async function showFileHistory(): Promise<void> {
    const editor = vscode.window.activeTextEditor;
    if (!editor) { vscode.window.showWarningMessage('[!] No active file'); return; }

    const filePath = editor.document.uri.fsPath;

    try {
        // The backend prints history as a table (it has no JSON form).
        const { stdout } = await client.runText([filePath, '--show-history'], path.dirname(filePath));
        outputChannel.appendLine('');
        outputChannel.appendLine(stdout.trimEnd());
        outputChannel.show(false);
    } catch (error) {
        vscode.window.showErrorMessage(`[-] Failed to load history: ${error}`);
    }
}

export async function installGitHook(): Promise<void> {
    const folders = vscode.workspace.workspaceFolders;
    if (!folders) { vscode.window.showWarningMessage('[!] No workspace folder open'); return; }

    if (!vscode.workspace.isTrusted) {
        vscode.window.showWarningMessage('[!] Installing a git hook needs a trusted workspace.');
        return;
    }
    const root = folders[0].uri.fsPath;

    try {
        // The CLI has no option for this; the backend installs the hook through
        // GitIntegration.install_pre_commit_hook (it reports False, and leaves
        // a foreign hook in place, when it cannot install). It writes where git
        // keeps hooks, which core.hooksPath, a worktree or a linked hook file
        // can put outside this folder: that needs an explicit yes.
        const target = await client.preCommitHookTarget(root);
        if (!target) {
            vscode.window.showWarningMessage('[!] No git repository here: the pre-commit hook was not installed.');
            return;
        }
        if (!isInside(target, root)) {
            const choice = await vscode.window.showWarningMessage(
                `The pre-commit hook would be written outside this folder: ${target} ` +
                '(git\'s hooks directory: core.hooksPath, a worktree or a linked hook). Install it there?',
                { modal: true }, 'Install',
            );
            if (choice !== 'Install') { return; }
        }
        const { installed, changed, output } = await client.installPreCommitHook(root, target);
        outputChannel.appendLine(output.trimEnd());
        if (changed) {
            vscode.window.showWarningMessage(
                '[!] The hook destination changed after it was checked: nothing was installed. Run the command again.');
            return;
        }
        if (!installed) {
            vscode.window.showWarningMessage(
                '[!] The pre-commit hook was not installed (a hook of another tool is there, or it could not be written). The reason is in the Output panel.');
            return;
        }
        vscode.window.showInformationMessage('[+] Git pre-commit hook installed successfully!');
    } catch (error) {
        vscode.window.showErrorMessage(`[-] Failed to install hook: ${error}`);
    }
}

export async function runCrossFileAnalysis(): Promise<void> {
    const folders = vscode.workspace.workspaceFolders;
    if (!folders) { vscode.window.showWarningMessage('[!] No workspace folder open'); return; }

    const rootPath = folders[0].uri.fsPath;

    statusBarItem.text = '$(sync~spin) SLOP: Cross-file analysis...';
    try {
        const { stdout } = await client.runText(
            [rootPath, '--project', '--cross-file'], rootPath,
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
    const rootPath = vscode.workspace.workspaceFolders?.[0]?.uri.fsPath ?? '.';

    statusBarItem.text = '$(sync~spin) SLOP: Loading trends...';
    try {
        // The backend prints trends as a table (it has no JSON form).
        const { stdout } = await client.runText(['--history-trends'], rootPath);
        outputChannel.appendLine('');
        outputChannel.appendLine(stdout.trimEnd());
        outputChannel.appendLine('');
        outputChannel.show(false);
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

    const rootPath = vscode.workspace.workspaceFolders?.[0]?.uri.fsPath ?? '.';

    statusBarItem.text = '$(sync~spin) SLOP: Exporting...';
    try {
        await client.runText(['--export-history', saveUri.fsPath], rootPath);
        vscode.window.showInformationMessage(`[+] History exported to ${saveUri.fsPath}`);
        statusBarItem.text = '$(check) SLOP: Ready';
    } catch (error) {
        const msg = error instanceof Error ? error.message : String(error);
        vscode.window.showErrorMessage(`[-] Export History failed: ${msg}`);
        statusBarItem.text = '$(error) SLOP: Error';
    }
}
