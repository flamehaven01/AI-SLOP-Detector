import * as vscode from 'vscode';
import { exec } from 'child_process';
import { promisify } from 'util';
import * as path from 'path';

const execAsync = promisify(exec);

let diagnosticCollection: vscode.DiagnosticCollection;
let statusBarItem: vscode.StatusBarItem;
let outputChannel: vscode.OutputChannel;
let lintOnTypeTimer: ReturnType<typeof setTimeout> | undefined;

export function activate(context: vscode.ExtensionContext) {
    outputChannel = vscode.window.createOutputChannel('SLOP Detector');
    context.subscriptions.push(outputChannel);

    outputChannel.appendLine('[*] AI SLOP Detector extension activated');

    diagnosticCollection = vscode.languages.createDiagnosticCollection('slop-detector');
    context.subscriptions.push(diagnosticCollection);

    // Status bar item
    statusBarItem = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Right, 100);
    statusBarItem.text = "$(check) SLOP: Ready";
    statusBarItem.show();
    context.subscriptions.push(statusBarItem);

    // Commands
    context.subscriptions.push(
        vscode.commands.registerCommand('slop-detector.analyzeFile', analyzeCurrentFile)
    );
    context.subscriptions.push(
        vscode.commands.registerCommand('slop-detector.analyzeWorkspace', analyzeWorkspace)
    );
    context.subscriptions.push(
        vscode.commands.registerCommand('slop-detector.showHistory', showFileHistory)
    );
    context.subscriptions.push(
        vscode.commands.registerCommand('slop-detector.installGitHook', installGitHook)
    );
    // v4.0 commands
    context.subscriptions.push(
        vscode.commands.registerCommand('slop-detector.autoFix', autoFixCurrentFile)
    );
    // v2.9.0 commands
    context.subscriptions.push(
        vscode.commands.registerCommand('slop-detector.showHistoryTrends', showHistoryTrends)
    );
    context.subscriptions.push(
        vscode.commands.registerCommand('slop-detector.exportHistory', exportHistory)
    );
    context.subscriptions.push(
        vscode.commands.registerCommand('slop-detector.showGate', showGateDecision)
    );
    context.subscriptions.push(
        vscode.commands.registerCommand('slop-detector.crossFileAnalysis', runCrossFileAnalysis)
    );
    // v3.2.x commands: LEDA self-calibration loop
    context.subscriptions.push(
        vscode.commands.registerCommand('slop-detector.initConfig', initConfig)
    );
    context.subscriptions.push(
        vscode.commands.registerCommand('slop-detector.selfCalibrate', selfCalibrate)
    );

    // Auto-lint on save
    context.subscriptions.push(
        vscode.workspace.onDidSaveTextDocument(document => {
            const config = vscode.workspace.getConfiguration('slopDetector');
            if (config.get('lintOnSave')) {
                analyzeDocument(document);
            }
        })
    );

    // Auto-lint on type with 1500ms debounce
    context.subscriptions.push(
        vscode.workspace.onDidChangeTextDocument(event => {
            const config = vscode.workspace.getConfiguration('slopDetector');
            if (config.get('lintOnType')) {
                if (lintOnTypeTimer !== undefined) {
                    clearTimeout(lintOnTypeTimer);
                }
                lintOnTypeTimer = setTimeout(() => {
                    lintOnTypeTimer = undefined;
                    analyzeDocument(event.document);
                }, 1500);
            }
        })
    );
}

async function analyzeCurrentFile() {
    const editor = vscode.window.activeTextEditor;
    if (!editor) {
        vscode.window.showWarningMessage('[!] No active file');
        return;
    }
    
    await analyzeDocument(editor.document);
}

async function analyzeDocument(document: vscode.TextDocument) {
    const config = vscode.workspace.getConfiguration('slopDetector');

    if (!config.get('enable')) {
        return;
    }

    const filePath = document.uri.fsPath;
    const supportedExtensions = ['.py', '.js', '.ts'];

    if (!supportedExtensions.some(ext => filePath.endsWith(ext))) {
        return;
    }

    outputChannel.appendLine(`[*] Analyzing: ${filePath}`);
    statusBarItem.text = "$(sync~spin) SLOP: Analyzing...";

    try {
        const result = await runSlopDetector(filePath, config);
        updateDiagnostics(document.uri, result);
        updateStatusBar(result);
        outputChannel.appendLine(`[+] Analysis complete: Deficit=${result.deficit_score}, Status=${result.status}`);
    } catch (error) {
        const errorMsg = error instanceof Error ? error.message : String(error);
        outputChannel.appendLine(`[!] Analysis failed: ${errorMsg}`);
        outputChannel.show(true);
        vscode.window.showErrorMessage(`SLOP Detector failed: ${errorMsg}`);
        statusBarItem.text = "$(error) SLOP: Error";
    }
}

/** Extract the first valid JSON object/array from stdout, ignoring [INFO] log lines. */
function extractJson(stdout: string): any {
    const idx = stdout.search(/^\s*[{[]/m);
    if (idx >= 0) {
        return JSON.parse(stdout.slice(idx));
    }
    return JSON.parse(stdout);
}

async function runSlopDetector(filePath: string, config: vscode.WorkspaceConfiguration): Promise<any> {
    const pythonPath = config.get('pythonPath', 'python');
    const configPath = config.get('configPath', '');
    const recordHistory = config.get('recordHistory', true);

    let command = `${pythonPath} -m slop_detector.cli "${filePath}" --json`;

    if (configPath) {
        command += ` --config "${configPath}"`;
    }
    if (!recordHistory) {
        command += ' --no-history';
    }

    outputChannel.appendLine(`[*] Running: ${command}`);

    const { stdout, stderr } = await execAsync(command, { maxBuffer: 10 * 1024 * 1024 });

    if (stderr) {
        outputChannel.appendLine(`[!] stderr: ${stderr}`);
    }

    return extractJson(stdout);
}

function updateDiagnostics(uri: vscode.Uri, result: any) {
    const diagnostics: vscode.Diagnostic[] = [];
    const config = vscode.workspace.getConfiguration('slopDetector');
    const failThreshold = config.get('failThreshold', 50.0);
    const warnThreshold = config.get('warnThreshold', 30.0);

    const deficitScore = result.deficit_score || 0;

    let overallSeverity = vscode.DiagnosticSeverity.Information;
    if (deficitScore >= failThreshold) {
        overallSeverity = vscode.DiagnosticSeverity.Error;
    } else if (deficitScore >= warnThreshold) {
        overallSeverity = vscode.DiagnosticSeverity.Warning;
    }

    // Clone Detection signal from pattern_issues
    const cloneIssues = (result.pattern_issues || []).filter(
        (i: any) => i.pattern_id === 'function_clone_cluster'
    );
    const clonePart = cloneIssues.length > 0
        ? `, Clone: ${cloneIssues[0].severity?.toUpperCase() ?? 'DETECTED'}`
        : '';

    // Purity score: exp(-0.5 * n_critical) — 4D LEDA dimension
    const nCritical = (result.pattern_issues ?? []).filter(
        (i: any) => (i.severity ?? '').toLowerCase() === 'critical'
    ).length;
    const purityScore = Math.exp(-0.5 * nCritical);

    // Overall summary diagnostic
    const mlPart = result.ml_score
        ? `, ML: ${(result.ml_score.slop_probability * 100).toFixed(0)}% [${result.ml_score.label}]`
        : '';
    const summaryMessage = `Code Quality Score: ${deficitScore.toFixed(1)}/100 — ${(result.status ?? 'unknown').toUpperCase()}${mlPart}${clonePart}\n` +
                          `LDR: ${(result.ldr?.ldr_score ?? 0).toFixed(3)}  ` +
                          `Inflation: ${(result.inflation?.inflation_score ?? 0).toFixed(3)}  ` +
                          `DDC: ${(result.ddc?.usage_ratio ?? 0).toFixed(3)}  ` +
                          `Purity: ${purityScore.toFixed(3)} (${nCritical} critical)`;

    const summaryDiagnostic = new vscode.Diagnostic(
        new vscode.Range(0, 0, 0, 0),
        summaryMessage,
        overallSeverity
    );
    summaryDiagnostic.source = 'SLOP Detector';
    diagnostics.push(summaryDiagnostic);

    // Add jargon-specific diagnostics
    if (result.inflation && result.inflation.jargon_details) {
        for (const jargon of result.inflation.jargon_details) {
            const line = Math.max(0, (jargon.line || 1) - 1);
            const message = `Unjustified jargon: "${jargon.word}" (${jargon.category})`;

            const diagnostic = new vscode.Diagnostic(
                new vscode.Range(line, 0, line, 1000),
                message,
                vscode.DiagnosticSeverity.Warning
            );
            diagnostic.source = 'SLOP Detector - Inflation';
            diagnostic.code = 'jargon';
            diagnostics.push(diagnostic);
        }
    }

    // Add docstring inflation diagnostics
    if (result.docstring_inflation && result.docstring_inflation.details) {
        for (const detail of result.docstring_inflation.details) {
            const line = Math.max(0, (detail.line || 1) - 1);
            const severity = (detail.severity || '').toLowerCase();

            let diagSeverity = vscode.DiagnosticSeverity.Warning;
            if (severity === 'critical') {
                diagSeverity = vscode.DiagnosticSeverity.Error;
            }

            const ratio = detail.ratio != null ? detail.ratio.toFixed(1) : '?';
            const message = `Docstring inflation: ${detail.name} (${detail.docstring_lines} doc / ${detail.implementation_lines} impl = ${ratio}x)`;

            const diagnostic = new vscode.Diagnostic(
                new vscode.Range(line, 0, line, 1000),
                message,
                diagSeverity
            );
            diagnostic.source = 'SLOP Detector - Docstring';
            diagnostic.code = 'docstring-inflation';
            diagnostics.push(diagnostic);
        }
    }

    // Add context jargon evidence diagnostics
    if (result.context_jargon && result.context_jargon.evidence_details) {
        for (const evidence of result.context_jargon.evidence_details) {
            if (evidence.is_justified === false) {
                const line = Math.max(0, (evidence.line || 1) - 1);
                const missing = Array.isArray(evidence.missing_evidence)
                    ? evidence.missing_evidence.join(', ')
                    : String(evidence.missing_evidence || 'unknown');
                const message = `"${evidence.jargon}" claim lacks evidence: ${missing}`;

                const diagnostic = new vscode.Diagnostic(
                    new vscode.Range(line, 0, line, 1000),
                    message,
                    vscode.DiagnosticSeverity.Warning
                );
                diagnostic.source = 'SLOP Detector - Evidence';
                diagnostic.code = 'unjustified-claim';
                diagnostics.push(diagnostic);
            }
        }
    }

    // Add unused import diagnostics
    if (result.ddc && result.ddc.unused && result.ddc.unused.length > 0) {
        const unusedImports = result.ddc.unused;
        const message = `Unused imports detected: ${unusedImports.join(', ')}`;

        const diagnostic = new vscode.Diagnostic(
            new vscode.Range(0, 0, 0, 1000),
            message,
            vscode.DiagnosticSeverity.Information
        );
        diagnostic.source = 'SLOP Detector - DDC';
        diagnostic.code = 'unused-import';
        diagnostics.push(diagnostic);
    }

    // Add hallucinated dependency diagnostics
    if (result.hallucination_deps &&
        result.hallucination_deps.hallucinated_deps &&
        result.hallucination_deps.hallucinated_deps.length > 0) {
        for (const dep of result.hallucination_deps.hallucinated_deps) {
            const message = `Hallucinated dependency: "${dep.name || dep}" - imported but serves no verified purpose`;

            const diagnostic = new vscode.Diagnostic(
                new vscode.Range(0, 0, 0, 1000),
                message,
                vscode.DiagnosticSeverity.Information
            );
            diagnostic.source = 'SLOP Detector - Hallucination';
            diagnostic.code = 'hallucinated-dep';
            diagnostics.push(diagnostic);
        }
    }

    // Add pattern-specific diagnostics (with suggestions)
    if (result.pattern_issues && Array.isArray(result.pattern_issues)) {
        for (const issue of result.pattern_issues) {
            const line = Math.max(0, (issue.line || 1) - 1);
            const severity = issue.severity?.toLowerCase() || 'medium';

            let diagSeverity = vscode.DiagnosticSeverity.Information;
            if (severity === 'critical') {
                diagSeverity = vscode.DiagnosticSeverity.Error;
            } else if (severity === 'high') {
                diagSeverity = vscode.DiagnosticSeverity.Warning;
            }

            let message = issue.message || 'Pattern issue detected';
            if (issue.suggestion) {
                message += `\nSuggestion: ${issue.suggestion}`;
            }

            const patternDiag = new vscode.Diagnostic(
                new vscode.Range(line, issue.column || 0, line, 1000),
                message,
                diagSeverity
            );
            patternDiag.source = 'SLOP Detector - Patterns';
            patternDiag.code = issue.pattern_id;
            diagnostics.push(patternDiag);
        }
    }

    diagnosticCollection.set(uri, diagnostics);
}

function updateStatusBar(result: any) {
    const deficitScore = result.deficit_score || 0;
    const status = result.status || 'unknown';

    let icon = '$(check)';
    let severityLabel = 'Good';
    if (deficitScore >= 50) {
        icon = '$(error)';
        severityLabel = 'Error';
    } else if (deficitScore >= 30) {
        icon = '$(warning)';
        severityLabel = 'Warning';
    }

    // Show severity level first, score in parentheses
    statusBarItem.text = `${icon} ${severityLabel} (${deficitScore.toFixed(1)})`;

    const ldrGrade = result.ldr?.grade ?? 'N/A';
    const mlTooltip = result.ml_score
        ? `- ML: ${(result.ml_score.slop_probability * 100).toFixed(0)}% [${result.ml_score.label}]\n`
        : '';
    const cloneIssuesSB = (result.pattern_issues ?? []).filter(
        (i: any) => i.pattern_id === 'function_clone_cluster'
    );
    const cloneTooltip = cloneIssuesSB.length > 0
        ? `- Clone: ${cloneIssuesSB[0].severity?.toUpperCase() ?? 'DETECTED'}\n`
        : '- Clone: PASS\n';
    const nCriticalSB = (result.pattern_issues ?? []).filter(
        (i: any) => (i.severity ?? '').toLowerCase() === 'critical'
    ).length;
    const puritySB = Math.exp(-0.5 * nCriticalSB);
    statusBarItem.tooltip = `SLOP Detector — ${severityLabel}\n` +
                           `Score: ${deficitScore.toFixed(1)}/100  Status: ${status}\n` +
                           `LDR Grade: ${ldrGrade}\n\n` +
                           `Metrics:\n` +
                           `- LDR: ${(result.ldr?.ldr_score ?? 0).toFixed(3)}\n` +
                           `- Inflation: ${(result.inflation?.inflation_score ?? 0).toFixed(3)}\n` +
                           `- DDC: ${(result.ddc?.usage_ratio ?? 0).toFixed(3)}\n` +
                           `- Purity: ${puritySB.toFixed(3)} (${nCriticalSB} critical)\n` +
                           cloneTooltip +
                           mlTooltip;
}

async function analyzeWorkspace() {
    const workspaceFolders = vscode.workspace.workspaceFolders;
    if (!workspaceFolders) {
        vscode.window.showWarningMessage('[!] No workspace folder open');
        return;
    }

    const rootPath = workspaceFolders[0].uri.fsPath;
    const config = vscode.workspace.getConfiguration('slopDetector');
    const pythonPath = config.get('pythonPath', 'python');

    statusBarItem.text = "$(sync~spin) SLOP: Analyzing workspace...";

    try {
        const command = `${pythonPath} -m slop_detector.cli "${rootPath}" --project --json`;
        const { stdout } = await execAsync(command, { 
            maxBuffer: 50 * 1024 * 1024,
            cwd: rootPath 
        });

        const result = extractJson(stdout);

        const statusIcon = result.overall_status === 'clean' ? '$(check)' : '$(warning)';
        statusBarItem.text = `${statusIcon} SLOP: ${result.avg_deficit_score.toFixed(1)} avg (${result.total_files} files)`;

        // Build QuickPick items — deficit files first, then summary
        const items: vscode.QuickPickItem[] = [];

        // Summary header (separator style)
        items.push({
            label: `$(graph) ${result.overall_status.toUpperCase()} — ${result.total_files} files, avg deficit ${result.avg_deficit_score.toFixed(1)}`,
            kind: vscode.QuickPickItemKind.Separator
        });

        // Deficit files, sorted by score descending
        const deficitFiles = (result.file_results ?? [])
            .filter((f: any) => f.status !== 'clean')
            .sort((a: any, b: any) => b.deficit_score - a.deficit_score);

        for (const f of deficitFiles) {
            const icon = f.deficit_score >= 50 ? '$(error)' : '$(warning)';
            const fileName = path.basename(f.file_path);
            items.push({
                label: `${icon} ${fileName}`,
                description: `${f.deficit_score.toFixed(1)}/100 — ${f.status.toUpperCase()}`,
                detail: `LDR: ${(f.ldr?.ldr_score ?? 0).toFixed(2)}  Inflation: ${(f.inflation?.inflation_score ?? 0).toFixed(2)}  DDC: ${(f.ddc?.usage_ratio ?? 0).toFixed(2)}`,
            });
        }

        if (deficitFiles.length === 0) {
            items.push({ label: '$(check) All files clean', description: 'No issues detected' });
        }

        const selected = await vscode.window.showQuickPick(items, {
            placeHolder: `Workspace: ${result.project_path} — click a file to open`,
            matchOnDescription: true,
            matchOnDetail: true,
        });

        // Navigate to selected file
        if (selected && selected.label && !selected.label.includes('All files')) {
            const fileName = selected.label.replace(/^\$\([^)]+\)\s*/, '');
            const matched = (result.file_results ?? []).find(
                (f: any) => path.basename(f.file_path) === fileName
            );
            if (matched) {
                const doc = await vscode.workspace.openTextDocument(matched.file_path);
                await vscode.window.showTextDocument(doc);
            }
        }
    } catch (error) {
        vscode.window.showErrorMessage(`[-] Workspace analysis failed: ${error}`);
        statusBarItem.text = "$(error) SLOP: Error";
    }
}

async function showFileHistory() {
    const editor = vscode.window.activeTextEditor;
    if (!editor) {
        vscode.window.showWarningMessage('[!] No active file');
        return;
    }

    const filePath = editor.document.uri.fsPath;
    const config = vscode.workspace.getConfiguration('slopDetector');
    const pythonPath = config.get('pythonPath', 'python');

    try {
        const command = `${pythonPath} -m slop_detector.cli "${filePath}" --show-history --json`;
        const { stdout } = await execAsync(command);

        const history = JSON.parse(stdout);

        if (history.length === 0) {
            vscode.window.showInformationMessage('[+] No history found for this file');
            return;
        }

        const items = history.map((entry: any) => ({
            label: `${entry.timestamp}`,
            description: `Deficit: ${entry.deficit_score?.toFixed(1) || entry.slop_score?.toFixed(1) || 'N/A'} (${entry.grade || entry.status || 'N/A'})`,
            detail: `LDR: ${entry.ldr_score?.toFixed(3) || 'N/A'}, Inflation: ${entry.inflation_score?.toFixed(3) || 'N/A'}, DDC: ${entry.ddc_usage_ratio?.toFixed(3) || 'N/A'}`
        }));

        vscode.window.showQuickPick(items, {
            placeHolder: 'File History'
        });

    } catch (error) {
        vscode.window.showErrorMessage(`[-] Failed to load history: ${error}`);
    }
}

async function installGitHook() {
    const workspaceFolders = vscode.workspace.workspaceFolders;
    if (!workspaceFolders) {
        vscode.window.showWarningMessage('[!] No workspace folder open');
        return;
    }

    const rootPath = workspaceFolders[0].uri.fsPath;
    const config = vscode.workspace.getConfiguration('slopDetector');
    const pythonPath = config.get('pythonPath', 'python');

    try {
        const command = `${pythonPath} -m slop_detector.cli --install-git-hook`;
        await execAsync(command, { cwd: rootPath });

        vscode.window.showInformationMessage('[+] Git pre-commit hook installed successfully!');
    } catch (error) {
        vscode.window.showErrorMessage(`[-] Failed to install hook: ${error}`);
    }
}

// v4.0: Auto-Fix
async function autoFixCurrentFile() {
    const editor = vscode.window.activeTextEditor;
    if (!editor) {
        vscode.window.showWarningMessage('[!] No active file');
        return;
    }

    const filePath = editor.document.uri.fsPath;
    if (!filePath.endsWith('.py')) {
        vscode.window.showWarningMessage('[!] Auto-fix is currently supported for Python files only');
        return;
    }

    const config = vscode.workspace.getConfiguration('slopDetector');
    const pythonPath = config.get('pythonPath', 'python');

    const choice = await vscode.window.showInformationMessage(
        'Auto-Fix: Apply fixes to detected slop patterns?',
        'Preview (dry-run)',
        'Apply Fixes',
        'Cancel'
    );

    if (!choice || choice === 'Cancel') {
        return;
    }

    const dryRunFlag = choice === 'Preview (dry-run)' ? '--dry-run' : '';
    const command = `${pythonPath} -m slop_detector.cli "${filePath}" --fix ${dryRunFlag}`;

    outputChannel.appendLine(`[*] Auto-Fix: ${command}`);
    statusBarItem.text = "$(sync~spin) SLOP: Fixing...";

    try {
        const { stdout, stderr } = await execAsync(command, { maxBuffer: 10 * 1024 * 1024 });
        outputChannel.appendLine(stdout);
        if (stderr) {
            outputChannel.appendLine(stderr);
        }

        const label = choice === 'Preview (dry-run)' ? 'Preview complete' : 'Fixes applied';
        vscode.window.showInformationMessage(`[+] ${label} - see Output panel for details`);
        outputChannel.show(false);

        if (choice !== 'Preview (dry-run)') {
            await analyzeDocument(editor.document);
        }
    } catch (error) {
        const msg = error instanceof Error ? error.message : String(error);
        vscode.window.showErrorMessage(`[-] Auto-Fix failed: ${msg}`);
        statusBarItem.text = "$(error) SLOP: Error";
    }
}

// v4.0: Gate Decision
async function showGateDecision() {
    const editor = vscode.window.activeTextEditor;
    if (!editor) {
        vscode.window.showWarningMessage('[!] No active file');
        return;
    }

    const filePath = editor.document.uri.fsPath;
    const config = vscode.workspace.getConfiguration('slopDetector');
    const pythonPath = config.get('pythonPath', 'python');
    const command = `${pythonPath} -m slop_detector.cli "${filePath}" --gate --json`;

    try {
        const { stdout } = await execAsync(command, { maxBuffer: 5 * 1024 * 1024 });
        const result = JSON.parse(stdout);
        const gate = result.gate_decision;

        if (gate) {
            const status = gate.allowed ? '[PASS]' : '[HALT]';
            const msg = `Gate ${status}: sr9=${gate.metrics_snapshot.sr9?.toFixed(3)} ` +
                        `di2=${gate.metrics_snapshot.di2?.toFixed(3)} ` +
                        `jsd=${gate.metrics_snapshot.jsd?.toFixed(3)} ` +
                        `ove=${gate.metrics_snapshot.ove?.toFixed(3)}`;
            if (gate.allowed) {
                vscode.window.showInformationMessage(msg);
            } else {
                vscode.window.showWarningMessage(`${msg}\n${gate.halt_reason || ''}`);
            }
        } else {
            outputChannel.appendLine(stdout);
            outputChannel.show(false);
        }
    } catch (error) {
        vscode.window.showErrorMessage(`[-] Gate check failed: ${error}`);
    }
}

// v4.0: Cross-File Analysis
async function runCrossFileAnalysis() {
    const workspaceFolders = vscode.workspace.workspaceFolders;
    if (!workspaceFolders) {
        vscode.window.showWarningMessage('[!] No workspace folder open');
        return;
    }

    const rootPath = workspaceFolders[0].uri.fsPath;
    const config = vscode.workspace.getConfiguration('slopDetector');
    const pythonPath = config.get('pythonPath', 'python');

    statusBarItem.text = "$(sync~spin) SLOP: Cross-file analysis...";

    const command = `${pythonPath} -m slop_detector.cli "${rootPath}" --project --cross-file`;

    try {
        const { stdout } = await execAsync(command, {
            maxBuffer: 20 * 1024 * 1024,
            cwd: rootPath
        });
        outputChannel.appendLine('[Cross-File Analysis]');
        outputChannel.appendLine(stdout);
        outputChannel.show(false);
        vscode.window.showInformationMessage('[+] Cross-file analysis complete - see Output panel');
        statusBarItem.text = "$(check) SLOP: Ready";
    } catch (error) {
        vscode.window.showErrorMessage(`[-] Cross-file analysis failed: ${error}`);
        statusBarItem.text = "$(error) SLOP: Error";
    }
}

// v2.9.0: History Trends
async function showHistoryTrends() {
    const config = vscode.workspace.getConfiguration('slopDetector');
    const pythonPath = config.get('pythonPath', 'python');

    statusBarItem.text = "$(sync~spin) SLOP: Loading trends...";

    try {
        const command = `${pythonPath} -m slop_detector.cli --history-trends --json`;
        const { stdout } = await execAsync(command, { maxBuffer: 5 * 1024 * 1024 });

        const trends = extractJson(stdout);

        outputChannel.appendLine('');
        outputChannel.appendLine('=== SLOP Detector — History Trends ===');
        outputChannel.appendLine('');

        // trends may be an object keyed by file path, or {files: [...]}
        const files: any[] = Array.isArray(trends)
            ? trends
            : trends.files ?? Object.values(trends);

        if (files.length === 0) {
            outputChannel.appendLine('  No history data found. Run analysis on files to build history.');
        } else {
            const colW = 40;
            const header = `${'File'.padEnd(colW)}  ${'Runs'.padStart(4)}  ${'Latest'.padStart(7)}  ${'Best'.padStart(7)}  ${'Worst'.padStart(7)}  Trend`;
            outputChannel.appendLine(header);
            outputChannel.appendLine('-'.repeat(header.length));

            for (const entry of files) {
                const name = path.basename(entry.file_path ?? entry.path ?? 'unknown').padEnd(colW).slice(0, colW);
                const runs  = String(entry.run_count ?? entry.total_runs ?? '?').padStart(4);
                const latest = (entry.latest_deficit ?? entry.last_score ?? 0).toFixed(1).padStart(7);
                const best   = (entry.best_deficit  ?? entry.min_score  ?? 0).toFixed(1).padStart(7);
                const worst  = (entry.worst_deficit ?? entry.max_score  ?? 0).toFixed(1).padStart(7);
                const latestNum = parseFloat(latest);
                const prevNum   = entry.previous_deficit ?? entry.prev_score ?? latestNum;
                const trend = latestNum < prevNum - 1 ? 'improving' : latestNum > prevNum + 1 ? 'degrading' : 'stable';
                outputChannel.appendLine(`${name}  ${runs}  ${latest}  ${best}  ${worst}  ${trend}`);
            }
        }

        outputChannel.appendLine('');
        outputChannel.show(false);
        vscode.window.showInformationMessage(`[+] History Trends — ${files.length} file(s). See Output panel.`);
        statusBarItem.text = "$(check) SLOP: Ready";
    } catch (error) {
        const msg = error instanceof Error ? error.message : String(error);
        vscode.window.showErrorMessage(`[-] History Trends failed: ${msg}`);
        statusBarItem.text = "$(error) SLOP: Error";
    }
}

// v2.9.0: Export History
async function exportHistory() {
    const saveUri = await vscode.window.showSaveDialog({
        defaultUri: vscode.Uri.file('slop_history.jsonl'),
        filters: { 'JSONL': ['jsonl'], 'All Files': ['*'] },
        saveLabel: 'Export History'
    });

    if (!saveUri) {
        return;
    }

    const config = vscode.workspace.getConfiguration('slopDetector');
    const pythonPath = config.get('pythonPath', 'python');
    const outputPath = saveUri.fsPath;

    statusBarItem.text = "$(sync~spin) SLOP: Exporting...";

    try {
        const command = `${pythonPath} -m slop_detector.cli --export-history "${outputPath}"`;
        await execAsync(command, { maxBuffer: 50 * 1024 * 1024 });

        vscode.window.showInformationMessage(`[+] History exported to ${outputPath}`);
        statusBarItem.text = "$(check) SLOP: Ready";
    } catch (error) {
        const msg = error instanceof Error ? error.message : String(error);
        vscode.window.showErrorMessage(`[-] Export History failed: ${msg}`);
        statusBarItem.text = "$(error) SLOP: Error";
    }
}

// v3.2.x: Bootstrap .slopconfig.yaml via --init
async function initConfig() {
    const workspaceFolders = vscode.workspace.workspaceFolders;
    if (!workspaceFolders) {
        vscode.window.showWarningMessage('[!] No workspace folder open');
        return;
    }

    const rootPath = workspaceFolders[0].uri.fsPath;
    const config = vscode.workspace.getConfiguration('slopDetector');
    const pythonPath = config.get('pythonPath', 'python');

    const configExists = await vscode.workspace.findFiles(
        new vscode.RelativePattern(workspaceFolders[0], '.slopconfig.yaml'),
        undefined, 1
    );

    if (configExists.length > 0) {
        const choice = await vscode.window.showWarningMessage(
            '.slopconfig.yaml already exists. Overwrite?',
            'Overwrite', 'Cancel'
        );
        if (choice !== 'Overwrite') {
            return;
        }
    }

    statusBarItem.text = "$(sync~spin) SLOP: Initializing config...";

    try {
        const command = `${pythonPath} -m slop_detector.cli --init "${rootPath}"${configExists.length > 0 ? ' --force-init' : ''}`;
        const { stdout, stderr } = await execAsync(command, {
            maxBuffer: 10 * 1024 * 1024,
            cwd: rootPath
        });

        outputChannel.clear();
        outputChannel.appendLine('=== SLOP Detector: Init Config ===');
        outputChannel.appendLine(stdout);
        if (stderr) { outputChannel.appendLine(stderr); }
        outputChannel.show(true);

        vscode.window.showInformationMessage(
            '[+] .slopconfig.yaml created. Open output for details.'
        );
        statusBarItem.text = "$(check) SLOP: Ready";
    } catch (error) {
        const msg = error instanceof Error ? error.message : String(error);
        vscode.window.showErrorMessage(`[-] Init config failed: ${msg}`);
        statusBarItem.text = "$(error) SLOP: Error";
    }
}

// v3.2.x: Run LEDA self-calibration loop
async function selfCalibrate() {
    const workspaceFolders = vscode.workspace.workspaceFolders;
    const rootPath = workspaceFolders?.[0]?.uri.fsPath ?? '.';

    const config = vscode.workspace.getConfiguration('slopDetector');
    const pythonPath = config.get('pythonPath', 'python');

    statusBarItem.text = "$(sync~spin) SLOP: Calibrating...";

    try {
        const command = `${pythonPath} -m slop_detector.cli --self-calibrate`;
        const { stdout, stderr } = await execAsync(command, {
            maxBuffer: 10 * 1024 * 1024,
            cwd: rootPath
        });

        outputChannel.clear();
        outputChannel.appendLine('=== SLOP Detector: Self-Calibration (LEDA) ===');
        outputChannel.appendLine(stdout);
        if (stderr) { outputChannel.appendLine(stderr); }
        outputChannel.show(true);

        const isInsufficient = stdout.includes('insufficient_data') || stdout.includes('Not enough');
        const isNoChange = stdout.includes('no_change') || stdout.includes('No change');

        if (isInsufficient) {
            vscode.window.showWarningMessage(
                '[!] Not enough history yet. Run more analyses to build up the calibration dataset.'
            );
        } else if (isNoChange) {
            vscode.window.showInformationMessage(
                '[=] Calibration complete: current weights are already optimal.'
            );
        } else {
            const choice = await vscode.window.showInformationMessage(
                '[*] Calibration ready. Apply new weights to .slopconfig.yaml?',
                'Apply', 'View Only'
            );

            if (choice === 'Apply') {
                const applyCmd = `${pythonPath} -m slop_detector.cli --self-calibrate --apply-calibration`;
                const { stdout: applyOut } = await execAsync(applyCmd, {
                    maxBuffer: 10 * 1024 * 1024,
                    cwd: rootPath
                });
                outputChannel.appendLine('\n--- Apply Calibration ---');
                outputChannel.appendLine(applyOut);
                vscode.window.showInformationMessage('[+] Weights applied to .slopconfig.yaml');
            }
        }

        statusBarItem.text = "$(check) SLOP: Ready";
    } catch (error) {
        const msg = error instanceof Error ? error.message : String(error);
        vscode.window.showErrorMessage(`[-] Self-calibration failed: ${msg}`);
        statusBarItem.text = "$(error) SLOP: Error";
    }
}

export function deactivate() {
    if (lintOnTypeTimer !== undefined) {
        clearTimeout(lintOnTypeTimer);
    }
    if (diagnosticCollection) {
        diagnosticCollection.dispose();
    }
    if (statusBarItem) {
        statusBarItem.dispose();
    }
}
