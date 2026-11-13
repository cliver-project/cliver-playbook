/**
 * Public surface of the rag-governance frontend package.
 *
 * The barrel carries what an app wires up once — routes, nav entries,
 * translations — plus the API wrappers, because a project that vendors or
 * re-skins the pages still needs the typed client. Components and pages are
 * reachable through deep paths
 * (`cliver-playbook-app-rag-governance/pages/GovOverviewPage.tsx`); deep
 * paths carry the source extension, which is the package's `exports`
 * contract and what makes cross-package imports work with no aliases
 * configured.
 */

export {
  activateRules,
  askGoverned,
  confirmGoldenSet,
  createProject,
  createSource,
  decideApproval,
  forkGoldenSet,
  generateGolden,
  getBatch,
  getEvalRun,
  getProject,
  importGolden,
  listApprovals,
  listBatches,
  listEvalRuns,
  listGoldenSets,
  listProjects,
  listRuleSets,
  listSources,
  listStaged,
  previewRules,
  proposeRules,
  startEvalRun,
  triggerIngest,
  type Approval,
  type Batch,
  type BatchStatus,
  type Citation,
  type EvalCaseResult,
  type EvalRun,
  type EvalRunDetail,
  type GoldenCase,
  type GoldenSet,
  type IntentRule,
  type Project,
  type QueryResponse,
  type RuleSet,
  type Source,
  type StagedDocument,
  type Strategy,
  type ToolCall,
} from "cliver-playbook-app-rag-governance/api/governance.ts";
export { govTranslations } from "cliver-playbook-app-rag-governance/locales/index.ts";
export { govNavItems } from "cliver-playbook-app-rag-governance/nav.ts";
export { govRoutes, govStandaloneRoutes } from "cliver-playbook-app-rag-governance/routes.tsx";
