/**
 * B6 — Pulse health dashboard (presentation contract: project summary header +
 * priority hotspots, deficit x churn x coverage). Styling via VS Code CSS theme
 * variables only; CSP nonce.
 */

import * as vscode from 'vscode';
import * as path from 'path';
import * as client from './client';
import type { PriorityHotspot } from './client';
import { escapeHtml as esc, nonce as makeNonce, severityToken } from './webviewUtil';

function coverageCell(ratio: number | null): string {
    return ratio === null || ratio === undefined ? 'n/a' : `${Math.round(ratio * 100)}%`;
}

function renderHtml(output: client.HealthOutput, nonce: string): string {
    const s = output.summary;
    const tok = severityToken(s?.overall_status ?? '');
    const sig = output.signals ?? { churn_analysis_available: false, coverage_analysis_available: false, priority_hotspots: 0 };
    const hotspots: PriorityHotspot[] = output.targets ?? [];

    const rows = hotspots
        .map((h) => `
        <tr>
          <td class="num">${(h.priority_score ?? 0).toFixed(1)}</td>
          <td>${esc(path.basename(h.file_path ?? ''))}</td>
          <td class="num">${(h.deficit_score ?? 0).toFixed(1)}</td>
          <td class="num">${h.churn_count ?? 0}</td>
          <td class="num">${coverageCell(h.coverage_ratio)}</td>
          <td class="reasons">${esc((h.reasons ?? []).join(', '))}</td>
        </tr>`)
        .join('');

    const body = hotspots.length
        ? `<table>
        <thead><tr><th class="num">prio</th><th>file</th><th class="num">deficit</th><th class="num">churn</th><th class="num">cov</th><th>reasons</th></tr></thead>
        <tbody>${rows}</tbody>
      </table>`
        : `<p class="note">No priority hotspots.</p>`;

    const churnNote = sig.churn_analysis_available ? '' : ' <span class="note">(churn data unavailable)</span>';
    const covNote = sig.coverage_analysis_available ? '' : ' <span class="note">(coverage data unavailable)</span>';

    return `<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'nonce-${nonce}';">
<style nonce="${nonce}">
  body { font-family: var(--vscode-font-family); color: var(--vscode-foreground); padding: 12px 16px; }
  .head { display:flex; align-items:baseline; gap:10px; }
  .badge { font-weight:700; color:${tok.color}; }
  .metrics { color: var(--vscode-descriptionForeground); margin:4px 0 14px; font-size:0.9em; }
  table { border-collapse: collapse; width:100%; }
  th, td { text-align:left; padding:4px 8px; border-bottom:1px solid var(--vscode-panel-border); font-size:0.9em; }
  th { color: var(--vscode-descriptionForeground); font-weight:600; }
  .num { text-align:right; font-variant-numeric: tabular-nums; }
  .reasons { color: var(--vscode-descriptionForeground); }
  .note { color: var(--vscode-descriptionForeground); font-style:italic; }
</style></head>
<body>
  <div class="head">
    <span class="badge">[${esc(tok.glyph)}] ${esc(tok.label)}</span>
    <span>weighted ${(s?.weighted_deficit_score ?? 0).toFixed(1)} · avg ${(s?.avg_deficit_score ?? 0).toFixed(1)}</span>
  </div>
  <div class="metrics">${esc(s?.project_path ?? '')}${churnNote}${covNote}</div>
  <h3>Priority Hotspots (deficit × churn × coverage)</h3>
  ${body}
</body></html>`;
}

let panel: vscode.WebviewPanel | undefined;

export async function showPulsePanel(): Promise<void> {
    const folders = vscode.workspace.workspaceFolders;
    if (!folders) {
        vscode.window.showWarningMessage('[!] No workspace folder open');
        return;
    }
    const root = folders[0].uri.fsPath;

    if (!panel) {
        panel = vscode.window.createWebviewPanel(
            'slopPulse',
            'Pulse',
            vscode.ViewColumn.Beside,
            { enableScripts: true },
        );
        panel.onDidDispose(() => { panel = undefined; });
    }
    panel.title = 'Pulse — health';
    panel.webview.html = `<!DOCTYPE html><body style="font-family:var(--vscode-font-family)">Computing health…</body>`;

    try {
        const output = await client.pulse(root);
        panel.webview.html = renderHtml(output, makeNonce());
    } catch (error) {
        const msg = error instanceof Error ? error.message : String(error);
        vscode.window.showErrorMessage(`[-] Pulse failed: ${msg}`);
    }
}
