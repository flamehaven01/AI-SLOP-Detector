import * as vscode from 'vscode';
import { statusBarItem } from './state';
import { candidateCount, channelLine } from './findings';

/** The file's score, its review candidates and whether the file changed after
 *  the analysis (then the numbers describe the previous content). */
export function updateStatusBar(result: any, changed = false): void {
    const deficitScore = result.deficit_score || 0;
    const status = result.status || 'unknown';

    let icon = '$(check)';
    let label = 'Good';
    if (deficitScore >= 50) { icon = '$(error)'; label = 'Error'; }
    else if (deficitScore >= 30) { icon = '$(warning)'; label = 'Warning'; }

    const review = candidateCount(result);
    statusBarItem.text = `${changed ? '$(history)' : icon} ${label} (${deficitScore.toFixed(1)})` +
        (review ? ` · ${review} review` : '') + (changed ? ' · changed' : '');

    const ldrGrade = result.ldr?.grade ?? 'N/A';
    const mlTooltip = result.ml_score
        ? `- ML: ${(result.ml_score.slop_probability * 100).toFixed(0)}% [${result.ml_score.label}]\n`
        : '';
    const cloneIssues = (result.pattern_issues ?? []).filter(
        (i: any) => i.pattern_id === 'function_clone_cluster'
    );
    const cloneLine = cloneIssues.length > 0
        ? `- Clone: ${cloneIssues[0].severity?.toUpperCase() ?? 'DETECTED'}\n`
        : '- Clone: PASS\n';
    const nCritical = (result.pattern_issues ?? []).filter(
        (i: any) => (i.severity ?? '').toLowerCase() === 'critical'
    ).length;
    const purity = Math.exp(-0.5 * nCritical);

    statusBarItem.tooltip =
        `SLOP Detector — ${label}\n` +
        `Score: ${deficitScore.toFixed(1)}/100  Status: ${status}\n` +
        `LDR Grade: ${ldrGrade}\n\n` +
        `Metrics:\n` +
        (result.language
            ? `- ${result.language}: LDR-equivalent ${(result.ldr?.ldr_score ?? 0).toFixed(3)}\n`
            : `- LDR: ${(result.ldr?.ldr_score ?? 0).toFixed(3)}\n` +
              `- Inflation: ${(result.inflation?.inflation_score ?? 0).toFixed(3)}\n` +
              `- DDC: ${(result.ddc?.usage_ratio ?? 0).toFixed(3)}\n`) +
        `- Purity: ${purity.toFixed(3)} (${nCritical} critical)\n` +
        cloneLine +
        mlTooltip +
        `\nMeasured: ${channelLine(result)}` +
        (review ? `\nReview candidates (not scored): ${review}` : '') +
        (changed ? '\n\nThe file changed after this analysis: save or run Analyze Current File.' : '');
}
