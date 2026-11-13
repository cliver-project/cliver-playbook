import { api } from "cliver-playbook-app-basic/api/client.ts";

/**
 * Governance-domain API calls.
 *
 * Every endpoint lives under `/rag-governance`; all calls go through
 * the shared axios instance (base URL, bearer injection, 401 redirect).
 *
 * The domain has no job endpoint: every asynchronous step (ingest, golden
 * generation, evaluation) is acknowledged with a 202 carrying the target row
 * id, and callers poll the row itself — `batches/{id}`, the project's golden
 * list, `evaluations/{id}`. Statuses below are the server's enums, spelled
 * out so pages can branch on them without stringly guesses.
 */

// ---------------------------------------------------------------------------
// Shared shapes
// ---------------------------------------------------------------------------

export type Strategy = "retrieval" | "tools" | "agentic" | "none";

export interface Project {
  id: string;
  slug: string;
  name: string;
  description: string;
  status: "draft" | "baseline_eval" | "active" | "paused" | "archived";
  approval_mode: "manual" | "auto" | "hybrid";
  collection_id: string;
  config: Record<string, unknown>;
  active_config_version: number | null;
  created_by: string;
  created_at: string;
  updated_at: string;
}

export interface Source {
  id: string;
  project_id: string;
  kind: "upload" | "directory" | "http" | "mcp";
  config: Record<string, unknown>;
  authority: string;
  sync_schedule: string | null;
  sync_enabled: boolean;
  max_staleness_seconds: number | null;
  status: string;
  last_run_at: string | null;
  created_at: string;
  updated_at: string;
}

export type BatchStatus =
  | "queued"
  | "running"
  | "staged"
  | "review_pending"
  | "approved"
  | "published"
  | "rejected"
  | "failed";

export interface Batch {
  id: string;
  project_id: string;
  source_id: string | null;
  status: BatchStatus;
  stats: Record<string, number>;
  eval_run_id: string | null;
  submitted_by: string;
  approved_by: string | null;
  approved_at: string | null;
  comment: string | null;
  created_at: string;
  updated_at: string;
}

export interface StagedDocument {
  id: string;
  logical_id: string | null;
  version: number;
  title: string;
  source_uri: string | null;
  mime_type: string;
  classification: number | null;
  published: boolean;
  chunk_count: number;
  metadata: Record<string, unknown>;
  created_at: string;
}

export interface Approval {
  id: string;
  batch_id: string;
  decision: "approve" | "reject";
  comment: string;
  actor_id: string;
  created_at: string;
}

export interface RuleClassifier {
  kind?: string;
  config?: {
    keywords?: string[];
    patterns?: string[];
    threshold?: number;
    case_sensitive?: boolean;
  };
}

export interface IntentRule {
  intent: string;
  description?: string;
  priority?: number;
  classifier?: RuleClassifier;
  scope?: Record<string, unknown>;
  retrieval?: {
    mode?: "dense" | "sparse" | "hybrid" | null;
    embedder?: string | null;
    top_k?: number | null;
    rerank_top_k?: number | null;
  };
  strategy?: Strategy;
  tools?: string[];
  snapshot_fallback?: boolean;
  refusal?: { message: string } | null;
}

export interface RuleSet {
  project_id: string;
  version: number | null;
  status: "proposed" | "active" | "archived" | null;
  eval_run_id: string | null;
  rules: IntentRule[];
}

export interface GoldenCase {
  id: string;
  question: string;
  expected_intent: string;
  expected_strategy?: Strategy | null;
  allowed_strategies?: Strategy[];
  expected_tools?: string[];
  expected_tool_args?: Record<string, Record<string, unknown>>;
  as_of?: string | null;
  expected_sources?: { logical_id: string; locator?: string | null }[];
  expected_answer_facts?: string[];
  numeric_tolerance?: number;
  run_as_clearance?: number;
  leak_probe_clearance?: number | null;
  forbidden_sources?: string[];
  tags?: string[];
  notes?: string;
}

export interface GoldenSet {
  id: string;
  project_id: string;
  version: number;
  status: "candidate" | "confirmed";
  source: string;
  created_by: string;
  confirmed_by: string | null;
  created_at: string;
  updated_at: string;
  cases: GoldenCase[];
}

export interface EvalRun {
  id: string;
  project_id: string;
  golden_set_id: string;
  rule_version: number | null;
  stage: string;
  status: "queued" | "running" | "passed" | "failed";
  metrics: Record<string, number>;
  summary: string;
  created_at: string;
  finished_at: string | null;
}

export interface EvalCaseResult {
  case_id: string;
  passed: boolean;
  details: Record<string, unknown>;
}

export interface EvalRunDetail extends EvalRun {
  cases: EvalCaseResult[];
}

export interface Citation {
  kind: "document" | "tool";
  ref: string;
  locator: string | null;
  as_of: string | null;
}

export interface ToolCall {
  name: string;
  args_fingerprint: string;
  as_of: string;
  row_count: number;
  latency_ms: number;
  error: string | null;
  is_snapshot: boolean;
  period: string | null;
}

export interface QueryResponse {
  text: string;
  intent: string | null;
  strategy: Strategy;
  citations: Citation[];
  tool_calls: ToolCall[];
  as_of: string;
  refused: boolean;
  rule_version: number | null;
}

// ---------------------------------------------------------------------------
// Projects
// ---------------------------------------------------------------------------

export function listProjects() {
  return api.get<{ items: Project[] }>("/rag-governance/projects").then((r) => r.data);
}

export function getProject(projectId: string) {
  return api.get<Project>(`/rag-governance/projects/${projectId}`).then((r) => r.data);
}

export function createProject(body: {
  slug: string;
  name: string;
  description?: string;
  approval_mode?: "manual" | "auto" | "hybrid";
  config?: Record<string, unknown>;
}) {
  return api
    .post<Project>("/rag-governance/projects", body)
    .then((r) => r.data);
}

// ---------------------------------------------------------------------------
// Sources and ingestion
// ---------------------------------------------------------------------------

export function listSources(projectId: string) {
  return api
    .get<{ items: Source[] }>(`/rag-governance/projects/${projectId}/sources`)
    .then((r) => r.data);
}

export function createSource(projectId: string, body: { kind: Source["kind"]; config?: Record<string, unknown> }) {
  return api
    .post<Source>(`/rag-governance/projects/${projectId}/sources`, body)
    .then((r) => r.data);
}

export function triggerIngest(sourceId: string) {
  // 202: the batch id is the polling handle, not a job endpoint.
  return api
    .post<{ batch_id: string; job_id: string; kind: string; status: string }>(
      `/rag-governance/sources/${sourceId}/ingest`,
    )
    .then((r) => r.data);
}

export function listBatches(projectId: string) {
  return api
    .get<{ items: Batch[] }>(`/rag-governance/projects/${projectId}/batches`)
    .then((r) => r.data);
}

export function getBatch(batchId: string) {
  return api.get<Batch>(`/rag-governance/batches/${batchId}`).then((r) => r.data);
}

export function listStaged(batchId: string) {
  return api
    .get<{ items: StagedDocument[] }>(`/rag-governance/batches/${batchId}/staged`)
    .then((r) => r.data);
}

// ---------------------------------------------------------------------------
// Approvals
// ---------------------------------------------------------------------------

export function decideApproval(batchId: string, decision: "approve" | "reject", comment = "") {
  return api
    .post<{ batch: Batch; approval: Approval }>(
      `/rag-governance/batches/${batchId}/approval`,
      { decision, comment },
    )
    .then((r) => r.data);
}

export function listApprovals(batchId: string) {
  return api
    .get<{ items: Approval[] }>(`/rag-governance/batches/${batchId}/approvals`)
    .then((r) => r.data);
}

// ---------------------------------------------------------------------------
// Golden sets
// ---------------------------------------------------------------------------

export function listGoldenSets(projectId: string) {
  return api
    .get<{ items: GoldenSet[] }>(`/rag-governance/projects/${projectId}/golden`)
    .then((r) => r.data);
}

export function importGolden(projectId: string, jsonl: string) {
  return api
    .post<GoldenSet>(`/rag-governance/projects/${projectId}/golden/import`, { jsonl })
    .then((r) => r.data);
}

export function generateGolden(projectId: string, scenario: string, maxCases = 10) {
  return api
    .post<{ job_id: string }>(`/rag-governance/projects/${projectId}/golden/generate`, {
      scenario,
      max_cases: maxCases,
    })
    .then((r) => r.data);
}

export function confirmGoldenSet(setId: string) {
  return api
    .post<GoldenSet>(`/rag-governance/golden/${setId}/confirm`)
    .then((r) => r.data);
}

export function forkGoldenSet(setId: string) {
  return api.post<GoldenSet>(`/rag-governance/golden/${setId}/fork`).then((r) => r.data);
}

// ---------------------------------------------------------------------------
// Intent rules
// ---------------------------------------------------------------------------

export function listRuleSets(projectId: string) {
  return api
    .get<{ items: RuleSet[] }>(`/rag-governance/projects/${projectId}/rules/versions`)
    .then((r) => r.data);
}

export function proposeRules(projectId: string, rules: IntentRule[]) {
  return api
    .post<RuleSet>(`/rag-governance/projects/${projectId}/rules/propose`, { rules })
    .then((r) => r.data);
}

export function activateRules(projectId: string, rules: IntentRule[], evalRunId: string) {
  return api
    .post<RuleSet>(`/rag-governance/projects/${projectId}/rules/activate`, {
      rules,
      eval_run_id: evalRunId,
    })
    .then((r) => r.data);
}

export function previewRules(projectId: string, question: string, rules?: IntentRule[]) {
  return api
    .post<{ matches: { intent: string; confidence: number; priority: number; strategy: Strategy }[] }>(
      `/rag-governance/projects/${projectId}/rules/preview`,
      rules ? { question, rules } : { question },
    )
    .then((r) => r.data);
}

// ---------------------------------------------------------------------------
// Evaluations
// ---------------------------------------------------------------------------

export function listEvalRuns(projectId: string) {
  return api
    .get<{ items: EvalRun[] }>(`/rag-governance/projects/${projectId}/evaluations`)
    .then((r) => r.data);
}

export function getEvalRun(runId: string) {
  return api
    .get<EvalRunDetail>(`/rag-governance/evaluations/${runId}`)
    .then((r) => r.data);
}

export function startEvalRun(
  projectId: string,
  body: { golden_set_id: string; rule_version?: number; stage?: string; batch_id?: string },
) {
  return api
    .post<{ job_id: string }>(`/rag-governance/projects/${projectId}/evaluations`, body)
    .then((r) => r.data);
}

// ---------------------------------------------------------------------------
// Governed query
// ---------------------------------------------------------------------------

export function askGoverned(
  projectId: string,
  question: string,
  asOf?: string,
  maxTokens?: number,
) {
  return api
    .post<QueryResponse>(`/rag-governance/projects/${projectId}/query`, {
      question,
      ...(asOf ? { as_of: asOf } : {}),
      ...(maxTokens ? { max_tokens: maxTokens } : {}),
    })
    .then((r) => r.data);
}
