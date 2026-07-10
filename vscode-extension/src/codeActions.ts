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

function _yamlQuote(value: string): string {
    return JSON.stringify(value.replace(/\r\n/g, '\n'));
}

function _topLevelSectionRange(
    doc: vscode.TextDocument,
    key: string,
): { headerLine: number; startLine: number; endLine: number } | undefined {
    const headerLine = [...Array(doc.lineCount).keys()].find(
        i => doc.lineAt(i).text.trimStart().startsWith(`${key}:`)
    );
    if (headerLine === undefined) {
        return undefined;
    }

    let endLine = headerLine + 1;
    while (endLine < doc.lineCount) {
        const text = doc.lineAt(endLine).text;
        const trimmed = text.trim();
        if (trimmed === '') {
            endLine += 1;
            continue;
        }
        const indent = text.length - text.trimStart().length;
        if (indent === 0) {
            break;
        }
        endLine += 1;
    }

    return { headerLine, startLine: headerLine + 1, endLine };
}

function _parseYamlScalar(raw: string): string {
    const trimmed = raw.trim();
    if (
        (trimmed.startsWith('"') && trimmed.endsWith('"')) ||
        (trimmed.startsWith("'") && trimmed.endsWith("'"))
    ) {
        try {
            return JSON.parse(trimmed);
        } catch {
            return trimmed.slice(1, -1);
        }
    }
    return trimmed;
}

function _sectionContainsValue(doc: vscode.TextDocument, key: string, value: string): boolean {
    const range = _topLevelSectionRange(doc, key);
    if (!range) {
        return false;
    }

    for (let i = range.startLine; i < range.endLine; i++) {
        const trimmed = doc.lineAt(i).text.trim();
        if (!trimmed.startsWith('- ')) {
            continue;
        }
        const current = _parseYamlScalar(trimmed.slice(2));
        if (current === value) {
            return true;
        }
    }
    return false;
}

async function _appendListEntry(
    doc: vscode.TextDocument,
    editor: vscode.TextEditor,
    key: string,
    value: string,
): Promise<'added' | 'exists'> {
    if (_sectionContainsValue(doc, key, value)) {
        return 'exists';
    }

    const quoted = _yamlQuote(value);
    const section = _topLevelSectionRange(doc, key);
    if (section) {
        const insertPos = new vscode.Position(section.endLine, 0);
        await editor.edit(eb => eb.insert(insertPos, `  - ${quoted}\n`));
        editor.selection = new vscode.Selection(insertPos, insertPos);
        editor.revealRange(new vscode.Range(insertPos, insertPos));
        return 'added';
    }

    const eof = doc.lineAt(doc.lineCount - 1).range.end;
    const prefix = doc.getText().endsWith('\n') ? '\n' : '\n\n';
    await editor.edit(eb => eb.insert(eof, `${prefix}${key}:\n  - ${quoted}\n`));
    editor.revealRange(new vscode.Range(eof, eof));
    return 'added';
}

async function _openPrimaryConfig(): Promise<vscode.TextEditor | undefined> {
    const folders = vscode.workspace.workspaceFolders;
    if (!folders) {
        return undefined;
    }

    const configFiles = await vscode.workspace.findFiles(
        new vscode.RelativePattern(folders[0], '.slopconfig.yaml'), undefined, 1
    );
    if (configFiles.length === 0) {
        vscode.window.showWarningMessage(
            '[!] No .slopconfig.yaml found. Run "Bootstrap .slopconfig.yaml" first.'
        );
        return undefined;
    }

    const doc = await vscode.workspace.openTextDocument(configFiles[0]);
    return vscode.window.showTextDocument(doc);
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
    const editor = await _openPrimaryConfig();
    if (!editor) {
        return;
    }

    const result = await _appendListEntry(
        editor.document,
        editor,
        'phantom_import_allowlist',
        moduleName,
    );
    if (result === 'exists') {
        vscode.window.showInformationMessage(
            `[=] '${moduleName}' is already present in phantom_import_allowlist`
        );
        return;
    }

    vscode.window.showInformationMessage(
        `[+] '${moduleName}' added to phantom_import_allowlist`
    );
}

export async function addFileToIgnore(relPath: string): Promise<void> {
    const editor = await _openPrimaryConfig();
    if (!editor) {
        return;
    }

    const result = await _appendListEntry(editor.document, editor, 'ignore', relPath);
    if (result === 'exists') {
        vscode.window.showInformationMessage(`[=] "${relPath}" is already present under ignore`);
        return;
    }

    vscode.window.showInformationMessage(
        `[+] "${relPath}" added to .slopconfig.yaml ignore`
    );
}
