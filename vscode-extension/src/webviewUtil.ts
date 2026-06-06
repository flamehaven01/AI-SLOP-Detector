/** Shared helpers for SLOP webview panels (kept in one place so the panels do
 *  not duplicate the same escape/nonce logic). */

export function escapeHtml(s: string): string {
    return s.replace(/[&<>"']/g, (c) => (
        { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c] as string
    ));
}

export function nonce(): string {
    return Math.random().toString(36).slice(2) + Date.now().toString(36);
}

export interface SeverityToken {
    glyph: string;
    label: string;
    color: string; // a --vscode-* variable reference
}

// Single source for severity tokens across panels (frozen presentation contract).
export function severityToken(status: string): SeverityToken {
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
