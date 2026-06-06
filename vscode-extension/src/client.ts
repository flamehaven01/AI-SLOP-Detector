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
 * JSON escape hatch for clean-JSON subcommands not yet on the typed surface
 * (e.g. `--gate --json`, `--show-history --json`). Parses stdout directly; do
 * not use when the command emits leading log lines (use runText + extractJson).
 */
export function runRaw<T = unknown>(args: string[], cwd: string): Promise<T> {
    return runJsonCommand<T>(args, options(cwd));
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
