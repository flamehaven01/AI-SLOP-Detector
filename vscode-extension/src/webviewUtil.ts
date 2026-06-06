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
