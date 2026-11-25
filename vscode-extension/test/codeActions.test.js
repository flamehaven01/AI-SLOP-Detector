// Run with `npm test`. The phantom_import Quick Fix "Allowlist '<module>'"
// reads the module name from the diagnostic message. 3.18.0 reworded that
// message ("... known provider supplies 'x'"), and the 3.17.0 extension found
// no name in it, so the action disappeared (VSX-01). The fixtures are real
// backend output (`scan <file> --format json`, paths replaced by /fixture).
const { test } = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const path = require('node:path');
const vscode = require('./vscode-stub.js');
const {
    initState, updateDiagnostics, SlopCodeActionProvider, extractModuleName, appendListEntry,
} = require('../.test-out/harness.js');

const SOURCE = 'SLOP Detector - Patterns';
const fixture = (name) => JSON.parse(fs.readFileSync(path.join(__dirname, 'fixtures', name), 'utf8'));

function diag(code, message, source = SOURCE) {
    const d = new vscode.Diagnostic(new vscode.Range(0, 0, 0, 1), message, 1);
    d.source = source;
    d.code = code;
    return d;
}

function actions(diagnostics) {
    const doc = { uri: vscode.Uri.file('/fixture/proj/app/imports.py') };
    return new SlopCodeActionProvider().provideCodeActions(doc, new vscode.Range(0, 0, 0, 0), { diagnostics });
}

function allowlisted(list) {
    return list.filter((a) => a.command?.command === 'slop-detector.addModuleToAllowlist')
        .map((a) => a.command.arguments[0]);
}

test('3.17.0 message: the module name is read', () => {
    assert.strictEqual(extractModuleName(
        "Phantom import: 'zzz_pkg' cannot be resolved (not in stdlib, builtins, or installed packages)"), 'zzz_pkg');
});

test('the guarded optional dependency message is still read', () => {
    assert.strictEqual(extractModuleName(
        "Undeclared optional dependency: 'orjson' is guarded with ImportError handling"), 'orjson');
});

test('3.18.0 message: the module name is read', () => {
    assert.strictEqual(extractModuleName(
        "Phantom import: no installed distribution, dependency declaration or known provider supplies 'zzz_pkg'"),
    'zzz_pkg');
});

test('a dotted import gives its top-level module', () => {
    assert.strictEqual(extractModuleName(
        "Phantom import: no installed distribution, dependency declaration or known provider supplies 'foo.bar'"),
    'foo');
    assert.strictEqual(extractModuleName("Phantom import: 'foo.bar' cannot be resolved"), 'foo');
});

test('a message without a module name gives none', () => {
    assert.strictEqual(extractModuleName('Phantom import: something else happened'), undefined);
    assert.strictEqual(extractModuleName("Declared dependency 'PIL' (provided by 'Pillow') is unavailable"), undefined);
});

test('another rule gets no allowlist action', () => {
    const list = actions([diag('runtime_unavailable_dependency',
        "Declared dependency 'PIL' (provided by 'Pillow') is unavailable in the analyzer's environment")]);
    assert.deepStrictEqual(allowlisted(list), []);
    assert.strictEqual(list.length, 0);
});

test('another diagnostic source gets no action', () => {
    const list = actions([diag('phantom_import',
        "Phantom import: no installed distribution, dependency declaration or known provider supplies 'x'",
        'SLOP Detector - Review')]);
    assert.strictEqual(list.length, 0);
});

test('a module already in the allowlist is not added twice', async () => {
    const lines = ['ignore:', '  - "a.py"', 'phantom_import_allowlist:', '  - "zzz_pkg"', ''];
    const doc = {
        lineCount: lines.length,
        lineAt: (i) => ({ text: lines[i], range: { end: new vscode.Position(i, lines[i].length) } }),
        getText: () => lines.join('\n'),
    };
    let edits = 0;
    const editor = { edit: () => { edits += 1; return Promise.resolve(true); }, revealRange() {} };
    assert.strictEqual(await appendListEntry(doc, editor, 'phantom_import_allowlist', 'zzz_pkg'), 'exists');
    assert.strictEqual(edits, 0);
    assert.strictEqual(await appendListEntry(doc, editor, 'phantom_import_allowlist', 'other'), 'added');
    assert.strictEqual(edits, 1);
});

for (const [version, expected] of [
    ['3.18.0', ['zzz_not_a_real_pkg_318']],
    ['3.17.0', ['zzz_not_a_real_pkg_318', 'PIL']],
]) {
    test(`backend ${version} scan -> diagnostics -> Quick Fix offers the allowlist`, () => {
        let stored = [];
        initState({ set: (_uri, d) => { stored = d; } }, { text: '' }, { appendLine() {} });
        updateDiagnostics(vscode.Uri.file('/fixture/proj/app/imports.py'),
            fixture(`backend-${version}-scan-imports.json`));
        const phantom = stored.filter((d) => d.code === 'phantom_import');
        assert.strictEqual(phantom.length, expected.length);
        const list = actions(stored);
        assert.deepStrictEqual(allowlisted(list), expected);
        // The other two actions of a phantom_import stay: output details, file ignore.
        assert.strictEqual(list.length, expected.length * 3);
    });
}
