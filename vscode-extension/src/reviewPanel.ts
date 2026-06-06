/**
 * B3 — diff-aware changed-code review (presentation contract). Surfaces the
 * `review` command: verdict, introduced-vs-inherited attribution (new slop is
 * what `introduced` flags), and the recommended actions. Styling via VS Code CSS
 * theme variables only; CSP nonce.
 */

import * as vscode from 'vscode';
import * as path from 'path';
import * as client from './client';
import type { AuditAction } from './client';
import { escapeHtml as esc, nonce as makeNonce } from './webviewUtil';

function verdictColor(verdict: string): string {
    if (verdict === 'pass') { return 'var(--vscode-charts-green)'; }
    if (verdict === 'warn') { return 'var(--vscode-charts-yellow)'; }
    return 'var(--vscode-errorForeground)'; // fail / unknown
}

function renderHtml(output: client.ReviewOutput, base: string, nonce: string): string {
    const verdict = String(output.verdict ?? '-');
    const attr = output.attribution ?? {
        introduced_files: [], inherited_files: [], introduced_count: 0, inherited_count: 0,
    };
    const actions: AuditAction[] = [...(output.actions ?? [])].sort(
        (a, b) => (b.priority_score ?? 0) - (a.priority_score ?? 0),
    );

    const actionRows = actions
        .map((a) => `
        <tr>
          <td class="num">${(a.priority_score ?? 0).toFixed(1)}</td>
          <td>${esc(a.kind ?? '')}</td>
          <td>${esc(path.basename(a.file_path ?? ''))}</td>
          <td class="reason">${esc(a.reason ?? '')}</td>
        </tr>`)
        .join('');

    const actionsBlock = actions.length
        ? `<table>
        <thead><tr><th class="num">prio</th><th>kind</th><th>file</th><th>reason</th></tr></thead>
        <tbody>${actionRows}</tbody>
      </table>`
        : `<p class="note">No recommended actions.</p>`;

    const introduced = attr.introduced_count ?? 0;
    const introMsg = introduced > 0
        ? `<span class="warn">${introduced} introduced</span> (new in changed code)`
        : `<span class="ok">0 introduced</span> — no new slop in changed code`;

    const baseLine = base
        ? `base: <code>${esc(base)}</code>`
        : `scope: changed files (no base ref)`;

    return `<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'nonce-${nonce}';">
<style nonce="${nonce}">
  body { font-family: var(--vscode-font-family); color: var(--vscode-foreground); padding: 12px 16px; }
  .head { display:flex; align-items:baseline; gap:10px; }
  .badge { font-weight:700; color:${verdictColor(verdict)}; text-transform:uppercase; }
  .sub { color: var(--vscode-descriptionForeground); font-size:0.9em; margin:4px 0; }
  .attr { margin:8px 0 14px; }
  .warn { color: var(--vscode-charts-orange); font-weight:600; }
  .ok { color: var(--vscode-charts-green); font-weight:600; }
  table { border-collapse: collapse; width:100%; }
  th, td { text-align:left; padding:4px 8px; border-bottom:1px solid var(--vscode-panel-border); font-size:0.9em; }
  th { color: var(--vscode-descriptionForeground); font-weight:600; }
  .num { text-align:right; font-variant-numeric: tabular-nums; }
  .reason { color: var(--vscode-descriptionForeground); }
  code { background: var(--vscode-textCodeBlock-background); padding:0 4px; border-radius:3px; }
  .note { color: var(--vscode-descriptionForeground); font-style:italic; }
</style></head>
<body>
  <div class="head">
    <span class="badge">${esc(verdict)}</span>
    ${output.should_fail_build ? '<span class="warn">would fail build</span>' : '<span class="ok">build ok</span>'}
  </div>
  <div class="sub">${baseLine}</div>
  <div class="attr">${introMsg} · ${attr.inherited_count ?? 0} inherited · ${(output.findings ?? []).length} findings</div>
  <h3>Recommended actions</h3>
  ${actionsBlock}
</body></html>`;
}

let panel: vscode.WebviewPanel | undefined;

export async function showReviewPanel(): Promise<void> {
    const folders = vscode.workspace.workspaceFolders;
    if (!folders) {
        vscode.window.showWarningMessage('[!] No workspace folder open');
        return;
    }
    const root = folders[0].uri.fsPath;

    const base = await vscode.window.showInputBox({
        title: 'Diff-aware Review',
        prompt: 'Git base ref to compare against (leave empty to review changed files)',
        placeHolder: 'e.g. origin/main, a tag, or empty',
    });
    if (base === undefined) {
        return; // cancelled
    }

    if (!panel) {
        panel = vscode.window.createWebviewPanel(
            'slopReview',
            'Changed-Code Review',
            vscode.ViewColumn.Beside,
            { enableScripts: true },
        );
        panel.onDidDispose(() => { panel = undefined; });
    }
    panel.title = base ? `Review — ${base}` : 'Review — changed';
    panel.webview.html = `<!DOCTYPE html><body style="font-family:var(--vscode-font-family)">Reviewing changed code…</body>`;

    try {
        const output = await client.review(root, base || undefined);
        panel.webview.html = renderHtml(output, base, makeNonce());
    } catch (error) {
        const msg = error instanceof Error ? error.message : String(error);
        vscode.window.showErrorMessage(`[-] Review failed: ${msg}`);
    }
}
