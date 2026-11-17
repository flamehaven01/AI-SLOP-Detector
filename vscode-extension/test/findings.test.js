// Run with `npm test`: bundles src/findings.ts (it imports only `path`) and
// checks how language results are read, without VS Code.
const { test } = require('node:test');
const assert = require('node:assert');
const { languageResults, projectFileResults } = require('../.test-out/findings.js');

// A backend project result: JS/TS results name their language, Go and Rust
// results do not (their list's key does).
const SCAN = {
    file_results: [],
    js_file_results: [{ file_path: 'web/a.ts', language: 'typescript', slop_score: 7, issues: [] }],
    go_file_results: [{ file_path: 'svc/main.go', slop_score: 10, issues: [] }],
    rust_file_results: [{ file_path: 'src/lib.rs', slop_score: 30, issues: [] }],
};

test('every language result names its language', () => {
    assert.deepStrictEqual(
        languageResults(SCAN).map((r) => r.language),
        ['typescript', 'go', 'rust'],
    );
});

test('a Go or Rust file is shown without the Python-only metrics', () => {
    // The views show "<language>: LDR-equivalent ..." for a result with a
    // language, and inflation/DDC (as 0) for one without: Go and Rust measure
    // neither (2026-11-16 VS Code check: lib.rs showed "Inflation: 0.000 DDC: 0.000").
    const files = projectFileResults(SCAN, '/p');
    const rust = files.find((f) => f.file_path.endsWith('lib.rs'));
    assert.strictEqual(rust.language, 'rust');
    assert.strictEqual(rust.deficit_score, 30);
});
