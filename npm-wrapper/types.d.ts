export type SlopStatus =
  | "clean"
  | "suspicious"
  | "inflated_signal"
  | "dependency_noise"
  | "critical_deficit";

export type JsonPrimitive = string | number | boolean | null;
export type JsonValue = JsonPrimitive | JsonObject | JsonValue[];
export interface JsonObject {
  [key: string]: JsonValue;
}

export interface LdrResult {
  total_lines: number;
  logic_lines: number;
  empty_lines: number;
  ldr_score: number;
  grade: string;
  is_abc_interface?: boolean;
  is_type_stub?: boolean;
  is_packaging_init?: boolean;
}

export interface InflationResult {
  jargon_count: number;
  avg_complexity: number;
  inflation_score: number;
  status: string;
  jargon_found: string[];
  jargon_details?: JsonObject[];
  justified_jargon?: string[];
  is_config_file?: boolean;
}

export interface DdcResult {
  imported: string[];
  actually_used: string[];
  unused: string[];
  fake_imports: string[];
  type_checking_imports: string[];
  usage_ratio: number;
  grade: string;
}

export interface SuppressionDirective {
  scope: string;
  action: string;
  lineno: number;
  rules: string[];
  source: string;
}

export interface SuppressionLedgerEntry {
  file_path: string;
  directive_line: number;
  suppressed_line: number;
  pattern_id: string;
  scope: string;
  matched_rule: string;
  source: string;
}

export interface MaskedIssue {
  file_path: string;
  masked_line: number;
  pattern_id: string;
  framework: string;
  rule_id: string;
  reason: string;
  source: string;
}

export interface PriorityHotspot {
  file_path: string;
  deficit_score: number;
  churn_count: number;
  churn_score: number;
  coverage_ratio: number | null;
  priority_score: number;
  reasons: string[];
}

export interface FileAnalysisOutput {
  file_path: string;
  ldr: LdrResult;
  inflation: InflationResult;
  ddc: DdcResult;
  deficit_score: number;
  status: SlopStatus;
  warnings: string[];
  pattern_issues: Array<JsonObject | string>;
  docstring_inflation?: JsonValue;
  hallucination_deps?: JsonValue;
  context_jargon?: JsonValue;
  ignored_functions?: JsonObject[];
  suppression_directives?: SuppressionDirective[];
  suppression_ledger?: SuppressionLedgerEntry[];
  masked_issues?: MaskedIssue[];
  ml_score?: JsonValue;
  dcf?: Record<string, number>;
  deficit_breakdown?: Record<string, number>;
}

export interface PolyglotFileOutput extends JsonObject {
  file_path?: string;
  status?: string;
}

export interface ScanOutput {
  project_path: string;
  total_files: number;
  deficit_files: number;
  clean_files: number;
  avg_deficit_score: number;
  weighted_deficit_score: number;
  avg_ldr: number;
  avg_inflation: number;
  avg_ddc: number;
  overall_status: SlopStatus;
  structural_coherence: number;
  coherence_level: string;
  suppressed_issue_count: number;
  suppression_ledger: SuppressionLedgerEntry[];
  priority_hotspots: PriorityHotspot[];
  churn_analysis_available: boolean;
  coverage_analysis_available: boolean;
  file_results: FileAnalysisOutput[];
  js_file_results: PolyglotFileOutput[];
  go_file_results: PolyglotFileOutput[];
}

export interface AuditAction {
  kind: string;
  file_path: string;
  priority_score: number;
  reason: string;
}

export interface AuditAttribution {
  introduced_files: string[];
  inherited_files: string[];
  introduced_count: number;
  inherited_count: number;
}

export interface AuditSummary {
  project_path: string;
  total_files: number;
  deficit_files: number;
  clean_files: number;
  avg_deficit_score: number;
  weighted_deficit_score: number;
  overall_status: SlopStatus;
}

export interface GateMetrics extends JsonObject {
  sr9?: number;
  di2?: number;
  jsd?: number;
  ove?: number;
}

export interface GateOutput extends JsonObject {
  verdict?: string;
  should_fail_build?: boolean;
  metrics?: GateMetrics;
}

export interface AuditOutput {
  command: "audit";
  verdict: string;
  should_fail_build: boolean;
  attribution: AuditAttribution;
  summary: AuditSummary;
  targets: PriorityHotspot[];
  actions: AuditAction[];
  findings: JsonObject[];
  gate: GateOutput;
}

export interface HealthSummary {
  project_path: string;
  overall_status: SlopStatus;
  weighted_deficit_score: number;
  avg_deficit_score: number;
  avg_ldr: number;
  avg_inflation: number;
  avg_ddc: number;
}

export interface HealthSignals {
  churn_analysis_available: boolean;
  coverage_analysis_available: boolean;
  priority_hotspots: number;
}

export interface HealthOutput {
  command: "health";
  summary: HealthSummary;
  targets: PriorityHotspot[];
  signals: HealthSignals;
}

export interface CleanupIssue extends JsonObject {
  file_path?: string;
  file_a?: string;
  file_b?: string;
  func_a?: string;
  func_b?: string;
  issue_type?: string;
  reason?: string;
  confidence?: number;
  action_class?: string;
  evidence?: JsonObject;
}

export interface CleanupSummary {
  project_path: string;
  issue_count: number;
  overall_status: SlopStatus;
}

export interface CleanupOutput {
  command:
    | "dead-code"
    | "dupes"
    | "unused-deps"
    | "stale-suppressions"
    | "boundary-violations";
  verdict: string;
  summary: CleanupSummary;
  issues: CleanupIssue[];
}

export interface ExplainOutput {
  command: "explain";
  identifier: string;
  summary: {
    category: string;
    message: string;
    mitigation: string;
  };
  mitigation: string;
}

export type CommandOutput =
  | ScanOutput
  | AuditOutput
  | HealthOutput
  | CleanupOutput
  | ExplainOutput;

export type ReviewOutput = AuditOutput;
export type PulseOutput = HealthOutput;
export type SweepOutput = CleanupOutput;
