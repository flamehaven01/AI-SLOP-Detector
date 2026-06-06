/**
 * B2 — Cleanup Plan panel (presentation contract). Surfaces the sweep family
 * (dead-code / dupes / unused-deps / stale-suppressions / boundary-violations)
 * as a confidence-ranked action plan with action_class tags and evidence.
 * Styling uses VS Code CSS theme variables only; CSP nonce.
 */

import * as vscode from 'vscode';
import * as path from 'path';
import * as client from './client';
import type { CleanupIssue } from './client';
import { escapeHtml as esc, nonce as makeNonce } from './webviewUtil';

const FAMILIES = [
    'dead-code',
    'dupes',
    'unused-deps',
    'stale-suppressions',
    'boundary-violations',
];

interface ActionToken {
    tag: string;
    color: string;
}

// action_class thresholds are fixed in operations.py:_classify_action
// (>=0.75 safe, >=0.45 needs, else unsafe). We only map them to tokens here.
function actionToken(actionClass: string | undefined): ActionToken {
    switch (actionClass) {
        case 'safe_review':
            return { tag: 'safe', color: 'var(--vscode-charts-green)' };
        case 'needs_review':
            return { tag: 'needs', color: 'var(--vscode-charts-yellow)' };
        case 'unsafe_auto_remove':
            return { tag: 'unsafe', color: 'var(--vscode-errorForeground)' };
        default:
            return { tag: '?', color: 'var(--vscode-foreground)' };
    }
}

function base(p: unknown): string {
    return typeof p === 'string' ? path.basename(p) : '';
}

function issueLocation(i: CleanupIssue): string {
    if (i.file_a && i.file_b) {
        return `${base(i.file_a)}::${i.func_a ?? ''} ↔ ${base(i.file_b)}::${i.func_b ?? ''}`;
    }
    if (typeof i.dependency === 'string') {
        return i.dependency;
    }
    if (i.file_path) {
        const unused = (i as Record<string, unknown>).unused;
        const suffix = Array.isArray(unused) && unused.length ? ` (unused: ${unused.join(', ')})` : '';
        return base(i.file_path) + suffix;
    }
    return (i.issue_type as string) ?? 'issue';
}

function issueEvidence(i: CleanupIssue): string {
    const ev = (i.evidence ?? {}) as Record<string, unknown>;
    const reasons = ev.reasons;
    if (Array.isArray(reasons) && reasons.length) {
        return reasons.map(String).join('; ');
    }
    if (typeof i.reason === 'string') {
        return i.reason;
    }
    if (typeof i.issue_type === 'string') {
        return i.issue_type;
    }
    return '';
}

function renderHtml(family: string, output: client.SweepOutput, nonce: string): string {
    const issues = [...(output.issues ?? [])].sort(
        (a, b) => (Number(b.confidence) || 0) - (Number(a.confidence) || 0),
    );
    const overallStatus = output.summary?.overall_status ?? '';

    const rowsHtml = issues
        .map((i) => {
            const tok = actionToken(i.action_class as string);
            const conf = (Number(i.confidence) || 0).toFixed(2);
            return `
        <div class="row">
          <span class="tag" style="background:${tok.color}">${esc(tok.tag)}</span>
          <span class="conf">${conf}</span>
          <span class="loc">${esc(issueLocation(i))}<span class="ev">${esc(issueEvidence(i))}</span></span>
        </div>`;
        })
        .join('');

    const body = issues.length
        ? rowsHtml
        : `<p class="note">✓ No ${esc(family)} findings.</p>`;

    return `<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'nonce-${nonce}';">
<style nonce="${nonce}">
  body { font-family: var(--vscode-font-family); color: var(--vscode-foreground); padding: 12px 16px; }
  .head { font-weight:600; margin-bottom:2px; }
  .sub { color: var(--vscode-descriptionForeground); font-size:0.9em; margin-bottom:12px; }
  .row { display:grid; grid-template-columns:64px 48px 1fr; align-items:start; gap:10px; margin:6px 0; }
  .tag { color: var(--vscode-editor-background); text-align:center; border-radius:3px; font-size:0.8em; font-weight:700; padding:1px 0; height:fit-content; }
  .conf { font-variant-numeric: tabular-nums; font-weight:600; }
  .loc { word-break:break-word; }
  .ev { display:block; color: var(--vscode-descriptionForeground); font-size:0.85em; }
  .note { color: var(--vscode-descriptionForeground); }
</style></head>
<body>
  <div class="head">Cleanup Plan — ${esc(family)}</div>
  <div class="sub">verdict: ${esc(String(output.verdict ?? '-'))} · ${issues.length} candidate(s) · ${esc(String(overallStatus))} · ranked by confidence</div>
  ${body}
</body></html>`;
}

let panel: vscode.WebviewPanel | undefined;

export async function showCleanupPanel(): Promise<void> {
    const folders = vscode.workspace.workspaceFolders;
    if (!folders) {
        vscode.window.showWarningMessage('[!] No workspace folder open');
        return;
    }
    const family = await vscode.window.showQuickPick(FAMILIES, {
        placeHolder: 'Select a cleanup family to plan',
    });
    if (!family) {
        return;
    }
    const root = folders[0].uri.fsPath;

    if (!panel) {
        panel = vscode.window.createWebviewPanel(
            'slopCleanup',
            'Cleanup Plan',
            vscode.ViewColumn.Beside,
            { enableScripts: true },
        );
        panel.onDidDispose(() => { panel = undefined; });
    }
    panel.title = `Cleanup — ${family}`;
    panel.webview.html = `<!DOCTYPE html><body style="font-family:var(--vscode-font-family)">Running sweep ${esc(family)}…</body>`;

    try {
        const output = await client.sweep(family, root);
        panel.webview.html = renderHtml(family, output, makeNonce());
    } catch (error) {
        const msg = error instanceof Error ? error.message : String(error);
        vscode.window.showErrorMessage(`[-] Cleanup Plan failed: ${msg}`);
    }
}
