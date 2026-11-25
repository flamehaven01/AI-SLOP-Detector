/**
 * Typed data layer over the `ai-slop-detector` npm wrapper.
 *
 * The extension does not spawn the Python backend by hand and does not parse
 * JSON manually; it consumes the wrapper's runtime API and the contract types.
 * pythonPath, configPath, recordHistory, and cwd are injected from settings so
 * config discovery and history project_id (sha256 of cwd) stay correct.
 */

import * as vscode from 'vscode';
import * as path from 'path';
import {
    runJsonCommand, runTextCommand, runCleanupFamily, computeHealth, reviewChanges,
} from 'ai-slop-detector';
import type {
    RunOptions, FileAnalysisOutput, ScanOutput, SweepOutput, CleanupIssue,
    HealthOutput, PriorityHotspot, ReviewOutput, AuditAction, TextResult,
} from 'ai-slop-detector';

export type {
    FileAnalysisOutput, ScanOutput, SweepOutput, CleanupIssue, HealthOutput,
    PriorityHotspot, ReviewOutput, AuditAction,
};

function pythonCandidate(): RunOptions['candidate'] {
    const pythonPath = vscode.workspace
        .getConfiguration('slopDetector')
        .get<string>('pythonPath', 'python');
    // Honor the configured interpreter exactly (matches the extension's prior
    // `<python> -m slop_detector.cli` invocation); bypasses auto-discovery.
    return { kind: 'module', command: pythonPath, args: ['-m', 'slop_detector.cli'] };
}

function options(cwd: string): RunOptions {
    return { cwd, candidate: pythonCandidate() };
}

function commonScanArgs(): string[] {
    const cfg = vscode.workspace.getConfiguration('slopDetector');
    const args: string[] = ['--format', 'json'];
    const configPath = cfg.get<string>('configPath', '');
    if (configPath) { args.push('--config', configPath); }
    if (!cfg.get<boolean>('recordHistory', true)) { args.push('--no-history'); }
    return args;
}

export function scanFile(filePath: string): Promise<FileAnalysisOutput> {
    return runJsonCommand<FileAnalysisOutput>(
        ['scan', filePath, ...commonScanArgs()],
        options(path.dirname(filePath)),
    );
}

export function scanProject(root: string): Promise<ScanOutput> {
    return runJsonCommand<ScanOutput>(['scan', root, ...commonScanArgs()], options(root));
}

export function sweep(family: string, root: string): Promise<SweepOutput> {
    return runCleanupFamily(family, root, options(root));
}

export function pulse(root: string): Promise<HealthOutput> {
    return computeHealth(root, options(root));
}

export function review(root: string, base?: string): Promise<ReviewOutput> {
    return reviewChanges(root, { ...options(root), ...(base ? { base } : {}) });
}

/**
 * Raw-text escape hatch for human-output commands (fix, init, calibrate,
 * git-hook, cross-file, export) and JSON commands that print log lines first.
 * Unifies all backend execution through the wrapper; the extension never spawns
 * the Python process by hand.
 */
export function runText(args: string[], cwd: string): Promise<TextResult> {
    return runTextCommand(args, options(cwd));
}

// Where install_pre_commit_hook(".") writes: the same git query and the same
// resolve() (core.hooksPath, worktrees and a linked hook file included); None
// outside a git repository.
const TARGET_OF = [
    'import subprocess, sys',
    'from pathlib import Path',
    'def target():',
    '    r = subprocess.run(["git", "rev-parse", "--git-path", "hooks"], capture_output=True, encoding="utf-8", errors="replace")',
    '    return None if r.returncode else str((Path(".") / r.stdout.strip() / "pre-commit").resolve())',
];

const HOOK_TARGET = [...TARGET_OF, 't = target()', 'sys.exit(1) if t is None else print(t)'].join('\n');

// Installs only when the destination, computed again just before the write,
// is the one confirmed (argv[1]); exit 3 when it changed in between.
const INSTALL_HOOK = [
    ...TARGET_OF,
    'from slop_detector.git_integration import GitIntegration',
    't = target()',
    'if t != sys.argv[1]:',
    '    print("[-] The hook destination changed after it was confirmed: " + str(t) + "; nothing installed")',
    '    sys.exit(3)',
    'sys.exit(0 if GitIntegration.install_pre_commit_hook(".") else 1)',
].join('\n');

function pythonCode(code: string): RunOptions['candidate'] {
    const pythonPath = vscode.workspace.getConfiguration('slopDetector').get<string>('pythonPath', 'python');
    return { kind: 'module', command: pythonPath, args: ['-c', code] };
}

/** The file the pre-commit hook would be written to for `root`; undefined
 *  when `root` is not in a git repository. */
export async function preCommitHookTarget(root: string): Promise<string | undefined> {
    try {
        const { stdout } = await runTextCommand([], { cwd: root, candidate: pythonCode(HOOK_TARGET) });
        return stdout.trim() || undefined;
    } catch (error: any) {
        if (error?.code === 1) { return undefined; }
        throw error;
    }
}

/**
 * Install the backend's git pre-commit hook in `root` (the CLI has no option
 * for it) at `confirmedTarget`, the destination preCommitHookTarget reported
 * and the user accepted. Runs the backend's own
 * GitIntegration.install_pre_commit_hook with the configured interpreter, in
 * the same process as a last check that the destination is still that one
 * (`changed` when it is not: nothing is written). The backend computes the
 * path itself, so a change after that check is not excluded. `output` is what
 * it printed (where the hook went, or why it did not install).
 */
export async function installPreCommitHook(
    root: string, confirmedTarget: string,
): Promise<{ installed: boolean; changed: boolean; output: string }> {
    try {
        const { stdout } = await runTextCommand([confirmedTarget], { cwd: root, candidate: pythonCode(INSTALL_HOOK) });
        return { installed: true, changed: false, output: stdout };
    } catch (error: any) {
        if (error?.code === 1 || error?.code === 3) {
            return { installed: false, changed: error.code === 3, output: `${error.stdout ?? ''}${error.stderr ?? ''}` };
        }
        throw error;
    }
}
