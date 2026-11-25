// The part of the `vscode` API the tested modules touch, for `npm test`
// without VS Code (esbuild aliases `vscode` to this file). Values are plain
// objects; nothing here imitates editor behavior beyond what a test asserts.
class Position {
    constructor(line, character) { this.line = line; this.character = character; }
}
class Range {
    constructor(a, b, c, d) {
        this.start = a instanceof Position ? a : new Position(a, b);
        this.end = a instanceof Position ? b : new Position(c, d);
    }
}
class Selection extends Range {}
class Diagnostic {
    constructor(range, message, severity) { this.range = range; this.message = message; this.severity = severity; }
}
class CodeAction {
    constructor(title, kind) { this.title = title; this.kind = kind; }
}
class EventEmitter {
    constructor() { this.event = () => undefined; }
    fire() {}
}
class RelativePattern {
    constructor(base, pattern) { this.base = base; this.pattern = pattern; }
}

const settings = {};
const messages = [];

module.exports = {
    Position, Range, Selection, Diagnostic, CodeAction, EventEmitter, RelativePattern,
    DiagnosticSeverity: { Error: 0, Warning: 1, Information: 2, Hint: 3 },
    CodeActionKind: { QuickFix: 'quickfix' },
    Uri: { file: (p) => ({ fsPath: p, path: p }) },
    workspace: {
        getConfiguration: () => ({ get: (key, fallback) => (key in settings ? settings[key] : fallback) }),
        asRelativePath: (uri) => String(uri.fsPath ?? uri).replace(/^.*[\\/]/, ''),
        workspaceFolders: undefined,
        textDocuments: [],
    },
    window: {
        showInformationMessage: (m) => { messages.push(m); return Promise.resolve(undefined); },
        showWarningMessage: (m) => { messages.push(m); return Promise.resolve(undefined); },
        showErrorMessage: (m) => { messages.push(m); return Promise.resolve(undefined); },
    },
    commands: { executeCommand: () => Promise.resolve(undefined) },
    languages: {},
    __settings: settings,
    __messages: messages,
};
