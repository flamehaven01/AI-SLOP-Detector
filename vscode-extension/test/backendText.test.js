// Run with `npm test`. "Show Gate Decision" read `gate_decision` from
// `--gate --json` with a strict JSON parse; the backend prints the decision as
// a text block after the JSON and has no such field, so the command failed on
// every backend (VSX-08). The fixtures are real backend stdout.
const { test } = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const path = require('node:path');
const { parseGateDecision, isInside } = require('../.test-out/harness.js');

const stdout = (name) => fs.readFileSync(path.join(__dirname, 'fixtures', name), 'utf8');

for (const version of ['3.17.0', '3.18.0']) {
    test(`backend ${version}: a passing gate is read`, () => {
        const gate = parseGateDecision(stdout(`backend-${version}-gate-stdout.txt`));
        assert.ok(gate);
        assert.strictEqual(gate.status, 'PASS');
        assert.strictEqual(gate.allowed, true);
        assert.match(gate.metrics, /^sr9=\d\.\d{4}  di2=/);
        assert.strictEqual(gate.halt, undefined);
        assert.ok(gate.block.startsWith('[Gate Decision]\n  Capability:'));
    });
}

test('a halting gate is read with its reason', () => {
    const gate = parseGateDecision(stdout('backend-3.18.0-gate-halt-stdout.txt'));
    assert.strictEqual(gate.status, 'HALT');
    assert.strictEqual(gate.allowed, false);
    assert.match(gate.halt, /^Gate HALT \[.*halt\.py\]: ldr=0\.385 < threshold=0\.6/);
    assert.ok(gate.notes.some((n) => n.startsWith('Recommend:')));
});

test('output without a gate block gives none', () => {
    assert.strictEqual(parseGateDecision('{"deficit_score": 1}\n'), undefined);
    assert.strictEqual(parseGateDecision('[Gate Decision]\n  Capability: PARTIAL\n'), undefined);
});

test('indented output after the block is not read as part of it', () => {
    const text = stdout('backend-3.18.0-gate-stdout.txt') + 'Other section\n  Status   : HALT\n  Halt     : not the gate\n';
    const gate = parseGateDecision(text);
    assert.strictEqual(gate.status, 'PASS');
    assert.strictEqual(gate.halt, undefined);
    assert.ok(!gate.block.includes('not the gate'));
});

test('a block with no Allowed, or an Allowed that is neither True nor False, gives none', () => {
    assert.strictEqual(parseGateDecision('[Gate Decision]\n  Status   : PASS\n  sr9=1.0000\n'), undefined);
    assert.strictEqual(parseGateDecision('[Gate Decision]\n  Status   : PASS\n  Allowed  : maybe\n'), undefined);
    assert.strictEqual(parseGateDecision('[Gate Decision]\n  Status   :\n  Allowed  : True\n'), undefined);
});

test('a contradictory or unknown gate state gives none', () => {
    assert.strictEqual(parseGateDecision('[Gate Decision]\n  Status   : HALT\n  Allowed  : True\n'), undefined);
    assert.strictEqual(parseGateDecision('[Gate Decision]\n  Status   : PASS\n  Allowed  : False\n'), undefined);
    assert.strictEqual(parseGateDecision('[Gate Decision]\n  Status   : WARN\n  Allowed  : True\n'), undefined);
    assert.strictEqual(parseGateDecision('[Gate Decision]\n  Status   : PASS\n  Allowed  : True\n').allowed, true);
    assert.strictEqual(parseGateDecision('[Gate Decision]\n  Status   : HALT\n  Allowed  : False\n').allowed, false);
});

test('isInside: a hook target inside or outside the workspace folder', () => {
    const w = String.raw;
    assert.strictEqual(isInside(w`C:\work\repo\.git\hooks\pre-commit`, w`c:\Work\Repo`, 'win32'), true);
    assert.strictEqual(isInside(w`C:\work\main\.git\hooks\pre-commit`, w`C:\work\repo`, 'win32'), false);
    assert.strictEqual(isInside(w`C:\work\repo-other\hooks\pre-commit`, w`C:\work\repo`, 'win32'), false);
    assert.strictEqual(isInside(w`D:\hooks\pre-commit`, w`C:\work\repo`, 'win32'), false);
    assert.strictEqual(isInside('/home/u/repo/.git/hooks/pre-commit', '/home/u/repo', 'linux'), true);
    assert.strictEqual(isInside('/home/u/shared-hooks/pre-commit', '/home/u/repo', 'linux'), false);
    assert.strictEqual(isInside('/home/u/Repo/.git/hooks/pre-commit', '/home/u/repo', 'linux'), false);
});
