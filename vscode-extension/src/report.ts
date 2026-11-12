import * as vscode from 'vscode';
import * as fs from 'fs';
import * as os from 'os';
import * as path from 'path';
import * as client from './client';
import { fileResults, outputChannel } from './state';
import { lineItems } from './findings';

type Format = 'html' | 'pdf' | 'md' | 'ai' | 'bundle';

interface FormatPick extends vscode.QuickPickItem { format: Format; ext: string }

const FORMATS: FormatPick[] = [
    { label: '$(globe) HTML report', description: 'one page; filters; prints to A4', format: 'html', ext: 'html' },
    { label: '$(file-pdf) PDF report (A4)', description: 'needs Chrome, Edge or Chromium installed', format: 'pdf', ext: 'pdf' },
    { label: '$(markdown) Markdown report', description: 'for a PR, an issue or a wiki', format: 'md', ext: 'md' },
    { label: '$(hubot) AI report (JSON Lines)', description: 'ai-slop-report/1 for an agent', format: 'ai', ext: 'jsonl' },
    { label: '$(folder) All reports', description: 'md, html, pdf, ai-report.jsonl and scan.json in one folder', format: 'bundle', ext: '' },
];

function scanTarget(): string | undefined {
    const folder = vscode.workspace.workspaceFolders?.[0]?.uri.fsPath;
    return folder ?? vscode.window.activeTextEditor?.document.uri.fsPath;
}

function historyArgs(): string[] {
    const cfg = vscode.workspace.getConfiguration('slopDetector');
    const args: string[] = [];
    const configPath = cfg.get<string>('configPath', '');
    if (configPath) { args.push('--config', configPath); }
    if (!cfg.get<boolean>('recordHistory', true)) { args.push('--no-history'); }
    return args;
}

function backendArgs(format: Format, target: string, out: string): string[] {
    const base = ['scan', target, ...historyArgs()];
    if (format === 'bundle') { return [...base, '--report-dir', out, '--quiet']; }
    if (format === 'ai') { return [...base, '--format', 'ai', '-o', out]; }
    return [...base, '-o', out];
}

/** The backend's own message for a failed export, in plain words. */
function explainFailure(error: any): string {
    const text = String(error?.stderr || error?.message || error);
    if (text.includes('ENV_BLOCKED')) {
        return 'PDF needs Chrome, Edge or Chromium installed (or the slop-detector setting SLOP_PDF_BROWSER). ' +
               'Export HTML instead and print it to PDF from a browser: it has the same A4 layout.';
    }
    if (/unrecognized arguments|invalid choice/.test(text)) {
        return 'This export needs the ai-slop-detector 3.14 backend or newer. Update it with ' +
               '`pip install -U ai-slop-detector`, or point slopDetector.pythonPath at an interpreter that has it.';
    }
    return text.split(/\r?\n/).filter((l) => l.trim()).slice(-3).join(' ');
}

async function openResult(format: Format, out: string): Promise<void> {
    if (format === 'html') {
        const choice = await vscode.window.showInformationMessage(
            `SLOP report written: ${path.basename(out)}`, 'Open in VS Code', 'Open in Browser');
        if (choice === 'Open in VS Code') { showReportPanel(out); }
        if (choice === 'Open in Browser') { await vscode.env.openExternal(vscode.Uri.file(out)); }
        return;
    }
    if (format === 'bundle') {
        const choice = await vscode.window.showInformationMessage(
            `SLOP reports written to ${out}`, 'Open HTML report', 'Reveal folder');
        if (choice === 'Open HTML report') { showReportPanel(path.join(out, 'report.html')); }
        if (choice === 'Reveal folder') { await vscode.commands.executeCommand('revealFileInOS', vscode.Uri.file(out)); }
        return;
    }
    const choice = await vscode.window.showInformationMessage(`SLOP report written: ${path.basename(out)}`, 'Open');
    if (choice !== 'Open') { return; }
    if (format === 'pdf') { await vscode.env.openExternal(vscode.Uri.file(out)); return; }
    const doc = await vscode.workspace.openTextDocument(out);
    await vscode.window.showTextDocument(doc, { preview: false });
    if (format === 'md') { await vscode.commands.executeCommand('markdown.showPreviewToSide', doc.uri); }
}

/** Command: write a report of the workspace (or the open file) in a chosen format. */
export async function exportReport(): Promise<void> {
    const target = scanTarget();
    if (!target) { vscode.window.showWarningMessage('Open a folder or a file to report on.'); return; }
    const pick = await vscode.window.showQuickPick(FORMATS, { placeHolder: 'Export the AI SLOP Detector report as...' });
    if (!pick) { return; }
    const root = vscode.workspace.workspaceFolders?.[0]?.uri ?? vscode.Uri.file(path.dirname(target));
    let out: string | undefined;
    if (pick.format === 'bundle') {
        out = path.join(root.fsPath, 'slop-report');
        const confirmed = await vscode.window.showInputBox({ prompt: 'Folder for the reports', value: out });
        out = confirmed || undefined;
    } else {
        const uri = await vscode.window.showSaveDialog({
            defaultUri: vscode.Uri.joinPath(root, `slop-report.${pick.ext}`),
            filters: { [pick.label.replace(/\$\([^)]*\)\s*/, '')]: [pick.ext] },
        });
        out = uri?.fsPath;
    }
    if (!out) { return; }
    const dest = out;
    try {
        await vscode.window.withProgress(
            { location: vscode.ProgressLocation.Notification, title: `AI SLOP Detector: writing ${pick.format.toUpperCase()} report` },
            () => client.runText(backendArgs(pick.format, target, dest), root.fsPath),
        );
    } catch (error) {
        const why = explainFailure(error);
        outputChannel.appendLine(`[!] Report export failed: ${String((error as any)?.stderr || error)}`);
        const retry = pick.format === 'pdf' ? 'Export HTML instead' : undefined;
        const choice = await vscode.window.showErrorMessage(`SLOP report not written: ${why}`, ...(retry ? [retry] : []));
        if (choice === 'Export HTML instead') { await exportFormat('html', target, root); }
        return;
    }
    await openResult(pick.format, dest);
}

async function exportFormat(format: Format, target: string, root: vscode.Uri): Promise<void> {
    const out = path.join(root.fsPath, `slop-report.${format}`);
    await client.runText(backendArgs(format, target, out), root.fsPath);
    await openResult(format, out);
}

let panel: vscode.WebviewPanel | undefined;

/** Show an HTML report file in a VS Code tab. */
export function showReportPanel(file: string): void {
    const html = fs.readFileSync(file, 'utf-8');
    if (!panel) {
        panel = vscode.window.createWebviewPanel(
            'slopReport', 'SLOP Report', vscode.ViewColumn.Beside,
            { enableScripts: true, localResourceRoots: [] },
        );
        panel.onDidDispose(() => { panel = undefined; });
    }
    panel.webview.html = html;
    panel.reveal();
}

/** Command: build the HTML report of the workspace (or the open file) and show it. */
export async function openReport(): Promise<void> {
    const target = scanTarget();
    if (!target) { vscode.window.showWarningMessage('Open a folder or a file to report on.'); return; }
    const root = vscode.workspace.workspaceFolders?.[0]?.uri.fsPath ?? path.dirname(target);
    const out = path.join(os.tmpdir(), `slop-report-${process.pid}.html`);
    try {
        await vscode.window.withProgress(
            { location: vscode.ProgressLocation.Notification, title: 'AI SLOP Detector: building the report' },
            () => client.runText(backendArgs('html', target, out), root),
        );
        showReportPanel(out);
    } catch (error) {
        vscode.window.showErrorMessage(`SLOP report not built: ${explainFailure(error)}`);
    }
}

/** Command (from a hover): copy one item as an ai-slop-report/1 style record. */
export async function copyItemForAgent(filePath: string, line: number, rule: string): Promise<void> {
    const result = fileResults.get(filePath);
    const item = result ? lineItems(result).find((i) => i.line === line && i.rule === rule) : undefined;
    if (!item) { vscode.window.showWarningMessage('The item is gone: analyze the file again.'); return; }
    const record = {
        record: 'item',
        kind: item.kind === 'finding' ? 'FINDING' : 'REVIEW_CANDIDATE',
        rule: item.rule,
        severity: item.kind === 'finding' ? item.severity : null,
        file: vscode.workspace.asRelativePath(filePath),
        line: item.line + 1,
        evidence: item.message,
        fix: item.suggestion || (item.kind === 'finding' ? 'MISSING' : 'NOT-APPLICABLE: decide in VERIFY first'),
        forbid: ['a suppression comment', 'a threshold or config change', 'deleting the function to make the item vanish'],
        prove: 're-scan the file: the item is gone, no new item appears, the tests pass',
    };
    await vscode.env.clipboard.writeText(JSON.stringify(record, null, 2));
    vscode.window.setStatusBarMessage('$(copy) SLOP item copied for an AI agent', 3000);
}
