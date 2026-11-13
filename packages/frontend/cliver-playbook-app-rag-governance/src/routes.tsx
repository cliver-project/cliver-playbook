import type { RouteObject } from "react-router-dom";

import { RequirePerm } from "cliver-playbook-app-user/components/auth/RequirePerm.tsx";

import GovApprovalsPage from "cliver-playbook-app-rag-governance/pages/GovApprovalsPage.tsx";
import GovEvaluationsPage from "cliver-playbook-app-rag-governance/pages/GovEvaluationsPage.tsx";
import GovGoldenPage from "cliver-playbook-app-rag-governance/pages/GovGoldenPage.tsx";
import GovOverviewPage from "cliver-playbook-app-rag-governance/pages/GovOverviewPage.tsx";
import GovQueryPage from "cliver-playbook-app-rag-governance/pages/GovQueryPage.tsx";
import GovRulesPage from "cliver-playbook-app-rag-governance/pages/GovRulesPage.tsx";
import GovSourcesPage from "cliver-playbook-app-rag-governance/pages/GovSourcesPage.tsx";

/**
 * The pages this package contributes, as children of the app's layout route
 * (`AuthAppLayout`) — hence the relative paths.
 *
 * Each page declares the permission its data needs through `RequirePerm`;
 * that is display gating only, the server enforces the same codes on every
 * endpoint. `govStandaloneRoutes` exists for symmetry with the other
 * packages (pages outside the authenticated chrome). This package has none
 * today — the governance loop always needs a session.
 */
export const govRoutes: RouteObject[] = [
  {
    path: "gov",
    element: (
      <RequirePerm code="rag_governance:project:read">
        <GovOverviewPage />
      </RequirePerm>
    ),
  },
  {
    path: "gov/rules",
    element: (
      <RequirePerm code="rag_governance:rule:read">
        <GovRulesPage />
      </RequirePerm>
    ),
  },
  {
    path: "gov/sources",
    element: (
      <RequirePerm code="rag_governance:project:read">
        <GovSourcesPage />
      </RequirePerm>
    ),
  },
  {
    path: "gov/approvals",
    element: (
      <RequirePerm code="rag_governance:staged:read">
        <GovApprovalsPage />
      </RequirePerm>
    ),
  },
  {
    path: "gov/golden",
    element: (
      <RequirePerm code="rag_governance:golden:read">
        <GovGoldenPage />
      </RequirePerm>
    ),
  },
  {
    path: "gov/evaluations",
    element: (
      <RequirePerm code="rag_governance:eval:read">
        <GovEvaluationsPage />
      </RequirePerm>
    ),
  },
  {
    path: "gov/query",
    element: (
      <RequirePerm code="rag_governance:query:read">
        <GovQueryPage />
      </RequirePerm>
    ),
  },
];

export const govStandaloneRoutes: RouteObject[] = [];
