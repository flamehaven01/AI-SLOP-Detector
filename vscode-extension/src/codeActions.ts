import * as vscode from 'vscode';
import * as path from 'path';

const PATTERN_SOURCE = 'SLOP Detector - Patterns';

// Patterns that get QuickFix actions.
const ACTIONABLE_PATTERNS = new Set(['phantom_import', 'god_function', 'lint_escape']);

// Parse module name from phantom_import diagnostic message.
// Matches: "Phantom import: 'module_name' cannot be resolved ..."
//      or: "Undeclared optional dependency: 'module_name' is guarded ..."
function _extractModuleName(message: string): string | undefined {
    const m = message.match(/['"]([A-Za-z_][\w.]*)['"](?:\s+cannot|\s+is guarded)/);
    return m ? m[1].split('.')[0] : undefined;
}

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
                const modName = _extractModuleName(diag.message);
                if (modName) {
                    actions.push(this._addToAllowlistAction(modName, diag));
                }
                actions.push(this._addToIgnoreAction(document, diag));
            } else if (code === 'god_function' || code === 'lint_escape') {
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

    private _addToAllowlistAction(moduleName: string, diag: vscode.Diagnostic): vscode.CodeAction {
        const action = new vscode.CodeAction(
            `SLOP: Allowlist '${moduleName}' — add to phantom_import_allowlist in .slopconfig.yaml`,
            vscode.CodeActionKind.QuickFix,
        );
        action.command = {
            command: 'slop-detector.addModuleToAllowlist',
            title: 'Add module to allowlist',
            arguments: [moduleName],
        };
        action.diagnostics = [diag];
        return action;
    }

    private _addToIgnoreAction(
        document: vscode.TextDocument,
        diag: vscode.Diagnostic,
    ): vscode.CodeAction {
        const relPath = vscode.workspace.asRelativePath(document.uri);
        const action  = new vscode.CodeAction(
            `SLOP: Suppress all issues — add "${path.basename(document.uri.fsPath)}" to .slopconfig.yaml ignore`,
            vscode.CodeActionKind.QuickFix,
        );
        action.command = {
            command: 'slop-detector.addFileToIgnore',
            title: 'Add file to ignore',
            arguments: [relPath],
        };
        action.diagnostics = [diag];
        return action;
    }
}

export async function addModuleToAllowlist(moduleName: string): Promise<void> {
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

    const doc    = await vscode.workspace.openTextDocument(configFiles[0]);
    const editor = await vscode.window.showTextDocument(doc);
    const lines  = [...Array(doc.lineCount).keys()];

    const allowlistIdx = lines.find(
        i => doc.lineAt(i).text.trimStart().startsWith('phantom_import_allowlist:')
    );

    if (allowlistIdx !== undefined) {
        const insertPos = new vscode.Position(allowlistIdx + 1, 0);
        await editor.edit(eb => eb.insert(insertPos, `  - ${moduleName}\n`));
        editor.selection = new vscode.Selection(insertPos, insertPos);
        editor.revealRange(new vscode.Range(insertPos, insertPos));
        vscode.window.showInformationMessage(
            `[+] '${moduleName}' added to phantom_import_allowlist`
        );
    } else {
        const endPos = new vscode.Position(doc.lineCount, 0);
        await editor.edit(eb =>
            eb.insert(endPos, `\nphantom_import_allowlist:\n  - ${moduleName}\n`)
        );
        editor.revealRange(new vscode.Range(endPos, endPos));
        vscode.window.showInformationMessage(
            `[+] phantom_import_allowlist created with '${moduleName}'`
        );
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
