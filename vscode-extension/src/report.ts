import * as vscode from 'vscode';
import * as fs from 'fs';
import * as os from 'os';
import * as path from 'path';
import * as client from './client';
import { fileResults, outputChannel } from './state';
import { lineItems } from './findings';
import { workOrderForItem } from './workorder';

type Format = 'html' | 'pdf' | 'md' | 'ai' | 'aimd' | 'bundle';

interface FormatPick extends vscode.QuickPickItem { format: Format; ext: string }

const FORMATS: FormatPick[] = [
    { label: '$(globe) HTML report', description: 'one page; filters; prints to A4', format: 'html', ext: 'html' },
    { label: '$(file-pdf) PDF report (A4)', description: 'needs Chrome, Edge or Chromium installed', format: 'pdf', ext: 'pdf' },
    { label: '$(markdown) Markdown report', description: 'for a PR, an issue or a wiki', format: 'md', ext: 'md' },
    {
        label: '$(hubot) AI work order (Markdown)',
        description: 'rules, evidence and a response form for an AI agent; auditor or agent mode',
        format: 'aimd', ext: 'md',
    },
    { label: '$(json) AI report (JSON Lines)', description: 'ai-slop-report/1, one record per item', format: 'ai', ext: 'jsonl' },
    {
        label: '$(folder) All reports',
        description: 'report.md, .html, .pdf, ai-report.jsonl, ai-report.md and scan.json in one folder',
        format: 'bundle', ext: '',
    },
];

/** How an AI work order is written (backend 3.14+ --format ai-md). */
interface WorkOrder { mode: 'auditor' | 'agent'; budget?: number }

async function askWorkOrder(): Promise<WorkOrder | undefined> {
    const modes = [
        { label: 'Auditor', description: 'default: code excerpts, read-only; the agent judges each item', mode: 'auditor' as const },
        {
            label: 'Agent', mode: 'agent' as const,
            description: 'no code copied; holds until its preconditions pass (operator approval, matching hashes, a test profile)',
        },
    ];
    const pick = await vscode.window.showQuickPick(modes, { placeHolder: 'AI work order mode' });
    if (!pick) { return undefined; }
    if (pick.mode === 'agent') { return { mode: 'agent' }; }
    const budget = await vscode.window.showInputBox({
        prompt: 'Token budget (estimated as characters / 4). Leave empty for every item in full.',
        validateInput: (v) => (v.trim() === '' || /^[1-9]\d*$/.test(v.trim()) ? undefined : 'a whole number, or empty'),
    });
    if (budget === undefined) { return undefined; }
    return { mode: 'auditor', budget: budget.trim() ? Number(budget.trim()) : undefined };
}

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

function workOrderArgs(order: WorkOrder): string[] {
    const args = ['--format', 'ai-md', '--ai-mode', order.mode];
    if (order.budget) { args.push('--ai-token-budget', String(order.budget)); }
    return args;
}

function backendArgs(format: Format, target: string, out: string, order?: WorkOrder): string[] {
    const base = ['scan', target, ...historyArgs()];
    if (format === 'bundle') { return [...base, '--report-dir', out, '--quiet']; }
    if (format === 'ai') { return [...base, '--format', 'ai', '-o', out]; }
    if (format === 'aimd') { return [...base, ...workOrderArgs(order ?? { mode: 'auditor' }), '-o', out]; }
    return [...base, '-o', out];
}

/** The backend's own message for a failed export, in plain words. */
function explainFailure(error: any): string {
    const text = String(error?.stderr || error?.message || error);
    if (text.includes('ENV_BLOCKED')) {
        return 'PDF needs Chrome, Edge or Chromium installed (or the slop-detector setting SLOP_PDF_BROWSER). ' +
               'Export HTML instead and print it to PDF from a browser: it has the same A4 layout.';
    }
    if (text.includes('BUDGET_UNSATISFIABLE')) {
        const line = text.split(/\r?\n/).find((l) => l.includes('BUDGET_UNSATISFIABLE')) ?? text;
        return line.replace(/^\[!\]\s*/, '').trim() + ' Give a larger budget, or none.';
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
    const order = pick.format === 'aimd' ? await askWorkOrder() : undefined;
    if (pick.format === 'aimd' && !order) { return; }
    const root = vscode.workspace.workspaceFolders?.[0]?.uri ?? vscode.Uri.file(path.dirname(target));
    let out: string | undefined;
    if (pick.format === 'bundle') {
        out = path.join(root.fsPath, 'slop-report');
        const confirmed = await vscode.window.showInputBox({ prompt: 'Folder for the reports', value: out });
        out = confirmed || undefined;
    } else {
        const name = pick.format === 'aimd' ? `ai-work-order-${order!.mode}.md` : `slop-report.${pick.ext}`;
        const uri = await vscode.window.showSaveDialog({
            defaultUri: vscode.Uri.joinPath(root, name),
            filters: { [pick.label.replace(/\$\([^)]*\)\s*/, '')]: [pick.ext] },
        });
        out = uri?.fsPath;
    }
    if (!out) { return; }
    const dest = out;
    try {
        await vscode.window.withProgress(
            { location: vscode.ProgressLocation.Notification, title: `AI SLOP Detector: writing the ${pick.label.replace(/\$\([^)]*\)\s*/, '')}` },
            () => client.runText(backendArgs(pick.format, target, dest, order), root.fsPath),
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

/** Command (from a hover): copy one item as a work order an AI agent can act
 *  on, cut from a fresh `--format ai-md` scan of the file (the mode follows
 *  slopDetector.workOrderMode). */
export async function copyItemForAgent(filePath: string, line: number, rule: string): Promise<void> {
    const result = fileResults.get(filePath);
    const item = result ? lineItems(result).find((i) => i.line === line && i.rule === rule) : undefined;
    if (!item) { vscode.window.showWarningMessage('The item is gone: analyze the file again.'); return; }
    const open = vscode.workspace.textDocuments.find((d) => d.uri.fsPath === filePath);
    if (open?.isDirty) {
        vscode.window.showWarningMessage('Save the file first: the work order is bound to the bytes on disk.');
        return;
    }
    const cfg = vscode.workspace.getConfiguration('slopDetector');
    const mode = cfg.get<string>('workOrderMode', 'auditor') === 'agent' ? 'agent' : 'auditor';
    const configPath = cfg.get<string>('configPath', '');
    // Written to a file, not read from stdout: the file is UTF-8 on every
    // backend, while the 3.14.0 backend's stdout follows the console code page
    // (cp949 on a Korean Windows rejects an em dash in a finding message;
    // fixed in 3.14.1).
    const out = path.join(os.tmpdir(), `slop-work-order-${process.pid}-${Date.now()}.md`);
    const args = ['scan', path.basename(filePath), '--format', 'ai-md', '--ai-mode', mode, '--no-history',
        ...(configPath ? ['--config', configPath] : []), '-o', out];
    let text: string | undefined;
    try {
        await client.runText(args, path.dirname(filePath));
        text = workOrderForItem(fs.readFileSync(out, 'utf-8'), path.basename(filePath), line, rule);
    } catch (error) {
        vscode.window.showErrorMessage(`Work order not built: ${explainFailure(error)}`);
        return;
    } finally {
        fs.rmSync(out, { force: true });
    }
    if (!text) {
        vscode.window.showWarningMessage('The file changed since this analysis and the item is not in a fresh work order: analyze it again.');
        return;
    }
    await vscode.env.clipboard.writeText(text);
    vscode.window.setStatusBarMessage(`$(copy) SLOP work order (${mode}) copied for an AI agent`, 4000);
}
