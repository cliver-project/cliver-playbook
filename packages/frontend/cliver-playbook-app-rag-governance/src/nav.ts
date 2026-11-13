import type { AuthedNavItem } from "cliver-playbook-app-user/layout/AuthAppLayout.tsx";

/**
 * The header entry this package adds to the app's navigation.
 *
 * One top-level "Governance" link (the loop overview) with the stages as a
 * second-level menu: seven top-level entries would crowd the header next to
 * every other package's pages. Child order is the demo storyline — overview,
 * semantics, ingestion, the approval gate, the yardstick, the gate runner,
 * the governed answer.
 *
 * Each entry names the permission that makes its page reachable; the layout
 * filters the list — children included — against the viewer's permissions,
 * and the server rejects the underlying calls whatever the header renders.
 */
export const govNavItems: AuthedNavItem[] = [
  {
    to: "/gov",
    labelKey: "nav.gov",
    end: true,
    perm: "rag_governance:project:read",
    children: [
      { to: "/gov/rules", labelKey: "nav.govRules", perm: "rag_governance:rule:read" },
      { to: "/gov/sources", labelKey: "nav.govSources", perm: "rag_governance:project:read" },
      { to: "/gov/approvals", labelKey: "nav.govApprovals", perm: "rag_governance:staged:read" },
      { to: "/gov/golden", labelKey: "nav.govGolden", perm: "rag_governance:golden:read" },
      {
        to: "/gov/evaluations",
        labelKey: "nav.govEvaluations",
        perm: "rag_governance:eval:read",
      },
      { to: "/gov/query", labelKey: "nav.govQuery", perm: "rag_governance:query:read" },
    ],
  },
];
