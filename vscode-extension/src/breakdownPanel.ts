/**
 * B1 — 4D + deficit_breakdown panel (presentation contract, penalty-attribution
 * primary). Renders why a file's deficit score is not 0.0 as a penalty bar chart
 * sourced from the engine's `deficit_breakdown`. Styling uses VS Code CSS theme
 * variables only (no webview-ui-toolkit, which is deprecated).
 */

import * as vscode from 'vscode';
import * as path from 'path';
import * as client from './client';
import type { FileAnalysisOutput } from './client';
import { escapeHtml as esc, nonce as makeNonce } from './webviewUtil';

interface SeverityToken {
    glyph: string;
    label: string;
    color: string; // a --vscode-* variable reference
}

// Single source for severity tokens (mirrors the frozen presentation contract).
function severityToken(status: string): SeverityToken {
    switch (status) {
        case 'clean':
            return { glyph: '✓', label: 'CLEAN', color: 'var(--vscode-charts-green)' };
        case 'suspicious':
            return { glyph: '!', label: 'SUSPICIOUS', color: 'var(--vscode-editorWarning-foreground)' };
        case 'inflated_signal':
            return { glyph: '~', label: 'INFLATED', color: 'var(--vscode-charts-orange)' };
        case 'dependency_noise':
            return { glyph: 'd', label: 'DEP-NOISE', color: 'var(--vscode-charts-purple)' };
        case 'critical_deficit':
            return { glyph: '×', label: 'CRITICAL', color: 'var(--vscode-errorForeground)' };
        default:
            return { glyph: '?', label: status.toUpperCase(), color: 'var(--vscode-foreground)' };
    }
}

interface PenaltyRow {
    label: string;
    penalty: number;
    raw: string; // pre-formatted secondary annotation
}

function derivePurity(result: FileAnalysisOutput): number {
    const nCritical = (result.pattern_issues ?? []).filter(
        (p) => typeof p === 'object' && p !== null && (p as any).severity === 'critical',
    ).length;
    return Math.exp(-0.5 * nCritical);
}

function buildRows(result: FileAnalysisOutput): { rows: PenaltyRow[]; total: number; hasBreakdown: boolean } {
    const bd = (result.deficit_breakdown ?? {}) as Record<string, number>;
    const hasBreakdown = Object.keys(bd).length > 0;
    const total = hasBreakdown ? (bd.total ?? result.deficit_score) : result.deficit_score;
    const rows: PenaltyRow[] = [
        { label: 'inflation', penalty: bd.inflation_penalty ?? 0, raw: `score ${(result.inflation?.inflation_score ?? 0).toFixed(2)}` },
        { label: 'ldr', penalty: bd.ldr_penalty ?? 0, raw: `score ${(result.ldr?.ldr_score ?? 0).toFixed(2)}` },
        { label: 'ddc', penalty: bd.ddc_penalty ?? 0, raw: `score ${(result.ddc?.usage_ratio ?? 0).toFixed(2)}` },
        { label: 'purity', penalty: bd.purity_penalty ?? 0, raw: `derived ${derivePurity(result).toFixed(2)}` },
        { label: 'pattern hits', penalty: bd.pattern_hits ?? 0, raw: `${(result.pattern_issues ?? []).length} findings` },
    ];
    return { rows, total, hasBreakdown };
}

function renderHtml(result: FileAnalysisOutput, nonce: string): string {
    const tok = severityToken(result.status);
    const { rows, total, hasBreakdown } = buildRows(result);
    const maxPenalty = Math.max(0, ...rows.map((r) => r.penalty));
    const barScale = total > 0 ? total : Math.max(1, maxPenalty);

    const rowHtml = rows
        .map((r) => {
            const pct = Math.min(100, (r.penalty / barScale) * 100);
            const driver = r.penalty === maxPenalty && maxPenalty > 0 ? ' ← top driver' : '';
            return `
        <div class="row">
          <div class="rlabel">${esc(r.label)}</div>
          <div class="track"><div class="fill" style="width:${pct.toFixed(1)}%"></div></div>
          <div class="rval">${r.penalty.toFixed(1)}<span class="raw">${esc(r.raw)}${driver}</span></div>
        </div>`;
        })
        .join('');

    const fallback = hasBreakdown
        ? ''
        : `<p class="note">deficit_breakdown unavailable (older CLI output) — showing raw scores only.</p>`;

    return `<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'nonce-${nonce}';">
<style nonce="${nonce}">
  body { font-family: var(--vscode-font-family); color: var(--vscode-foreground); padding: 12px 16px; }
  .head { display:flex; align-items:baseline; gap:10px; margin-bottom:4px; }
  .badge { font-weight:600; color:${tok.color}; }
  .score { font-size:1.4em; font-weight:700; }
  .file { color: var(--vscode-descriptionForeground); font-size:0.9em; word-break:break-all; }
  h3 { margin:16px 0 8px; font-size:0.95em; font-weight:600; }
  .row { display:grid; grid-template-columns:90px 1fr 150px; align-items:center; gap:10px; margin:5px 0; }
  .rlabel { text-align:right; color: var(--vscode-descriptionForeground); }
  .track { background: var(--vscode-input-background); border:1px solid var(--vscode-input-border); height:14px; border-radius:3px; overflow:hidden; }
  .fill { height:100%; background:${tok.color}; }
  .rval { font-variant-numeric: tabular-nums; font-weight:600; }
  .raw { display:block; font-weight:400; font-size:0.82em; color: var(--vscode-descriptionForeground); }
  .total { margin-top:10px; padding-top:8px; border-top:1px solid var(--vscode-panel-border); font-weight:700; }
  .note { color: var(--vscode-descriptionForeground); font-style:italic; font-size:0.85em; }
</style></head>
<body>
  <div class="head">
    <span class="badge">[${esc(tok.glyph)}] ${esc(tok.label)}</span>
    <span class="score">${total.toFixed(1)}</span>
  </div>
  <div class="file">${esc(result.file_path)}</div>
  <h3>Why not 0.0 — penalty attribution (sum = total)</h3>
  ${fallback}
  ${rowHtml}
  <div class="total">total &nbsp; ${total.toFixed(1)}</div>
</body></html>`;
}

let panel: vscode.WebviewPanel | undefined;

export async function showBreakdownPanel(): Promise<void> {
    const editor = vscode.window.activeTextEditor;
    if (!editor) {
        vscode.window.showWarningMessage('[!] No active file to analyze');
        return;
    }
    const filePath = editor.document.uri.fsPath;
    if (!['.py', '.js', '.ts', '.go'].some((e) => filePath.endsWith(e))) {
        vscode.window.showWarningMessage('[!] 4D Breakdown supports .py/.js/.ts/.go files');
        return;
    }

    if (!panel) {
        panel = vscode.window.createWebviewPanel(
            'slopBreakdown',
            '4D Breakdown',
            vscode.ViewColumn.Beside,
            { enableScripts: true },
        );
        panel.onDidDispose(() => { panel = undefined; });
    }
    panel.title = `4D — ${path.basename(filePath)}`;
    panel.webview.html = `<!DOCTYPE html><body style="font-family:var(--vscode-font-family)">Analyzing…</body>`;

    try {
        const result = await client.scanFile(filePath);
        panel.webview.html = renderHtml(result, makeNonce());
    } catch (error) {
        const msg = error instanceof Error ? error.message : String(error);
        vscode.window.showErrorMessage(`[-] 4D Breakdown failed: ${msg}`);
    }
}
