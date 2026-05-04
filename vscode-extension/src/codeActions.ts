import * as vscode from 'vscode';
import * as path from 'path';

const PATTERN_SOURCE = 'SLOP Detector - Patterns';

// Patterns that get QuickFix actions. phantom_import is CRITICAL by design —
// it means the CLI could not resolve the import via any of its 4 resolution paths.
const ACTIONABLE_PATTERNS = new Set(['phantom_import', 'god_function', 'lint_escape']);

export class SlopCodeActionProvider implements vscode.CodeActionProvider {
    static readonly providedCodeActionKinds = [vscode.CodeActionKind.QuickFix];

    provideCodeActions(
        document: vscode.TextDocument,
        _range: vscode.Range,
        context: vscode.CodeActionContext,
    ): vscode.CodeAction[] {
        const actions: vscode.CodeAction[] = [];

        for (const diag of context.diagnostics) {
            if (diag.source !== PATTERN_SOURCE) { continue; }
            const code = typeof diag.code === 'string' ? diag.code : '';
            if (!ACTIONABLE_PATTERNS.has(code)) { continue; }

            if (code === 'phantom_import') {
                actions.push(this._showOutputAction(diag));
                actions.push(this._addToIgnoreAction(document, diag));
            } else if (code === 'god_function') {
                actions.push(this._showOutputAction(diag));
            } else if (code === 'lint_escape') {
                actions.push(this._showOutputAction(diag));
            }
        }

        return actions;
    }

    private _showOutputAction(diag: vscode.Diagnostic): vscode.CodeAction {
        const action = new vscode.CodeAction(
            'SLOP: Show resolution details in Output panel',
            vscode.CodeActionKind.QuickFix,
        );
        action.command = { command: 'slop-detector.showOutput', title: 'Show Output' };
        action.diagnostics = [diag];
        return action;
    }

    private _addToIgnoreAction(
        document: vscode.TextDocument,
        diag: vscode.Diagnostic,
    ): vscode.CodeAction {
        const relPath = vscode.workspace.asRelativePath(document.uri);
        const action  = new vscode.CodeAction(
            `SLOP: Suppress phantom_import — add "${path.basename(document.uri.fsPath)}" to .slopconfig.yaml ignore`,
            vscode.CodeActionKind.QuickFix,
        );
        action.command = {
            command: 'slop-detector.addFileToIgnore',
            title: 'Add to ignore',
            arguments: [relPath],
        };
        action.diagnostics = [diag];
        return action;
    }
}

export async function addFileToIgnore(relPath: string): Promise<void> {
    const folders = vscode.workspace.workspaceFolders;
    if (!folders) { return; }

    const configFiles = await vscode.workspace.findFiles(
        new vscode.RelativePattern(folders[0], '.slopconfig.yaml'), undefined, 1
    );

    if (configFiles.length === 0) {
        vscode.window.showWarningMessage(
            '[!] No .slopconfig.yaml found. Run "Bootstrap .slopconfig.yaml" first.'
        );
        return;
    }

    // Open the file and show the line to add — safe, no YAML mutation
    const doc = await vscode.workspace.openTextDocument(configFiles[0]);
    const editor = await vscode.window.showTextDocument(doc);

    const ignoreLineIdx = [...Array(doc.lineCount).keys()].find(
        i => doc.lineAt(i).text.trimStart().startsWith('ignore:')
    );

    if (ignoreLineIdx !== undefined) {
        const pos = new vscode.Position(ignoreLineIdx + 1, 0);
        editor.selection = new vscode.Selection(pos, pos);
        editor.revealRange(new vscode.Range(pos, pos));
    }

    vscode.window.showInformationMessage(
        `Add this line under "ignore:" in .slopconfig.yaml:\n  - "${relPath}"`
    );
}
