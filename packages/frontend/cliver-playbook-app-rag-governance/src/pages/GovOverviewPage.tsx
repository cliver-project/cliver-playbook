import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";
import {
  ClipboardCheckIcon,
  DatabaseIcon,
  GitBranchIcon,
  MessageSquareIcon,
  ScrollTextIcon,
  ShieldCheckIcon,
} from "lucide-react";

import { AlertCircleIcon } from "lucide-react";
import { Button } from "cliver-playbook-app-basic/components/ui/button.tsx";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "cliver-playbook-app-basic/components/ui/card.tsx";
import {
  listBatches,
  listEvalRuns,
  listGoldenSets,
  listRuleSets,
  listSources,
} from "cliver-playbook-app-rag-governance/api/governance.ts";
import { ProjectPicker } from "cliver-playbook-app-rag-governance/components/gov/ProjectPicker.tsx";
import { StatusBadge } from "cliver-playbook-app-rag-governance/components/gov/StatusBadge.tsx";
import { useCurrentProject } from "cliver-playbook-app-rag-governance/components/gov/useProject.ts";

/**
 * The governance loop on one screen.
 *
 * This is the demo's table of contents: one card per stage of the loop, each
 * carrying the stage's live state and a link into its page. A presenter
 * walks the cards in order — define semantics, ingest, approve, gate on the
 * golden set, activate, answer — and every card answers "where are we right
 * now" without navigating.
 *
 * All lists are already per-project and small (a demo project has one digit
 * of each); the page reads them through react-query and lets the visitor
 * refresh by refocusing, exactly like the other governance pages.
 */
export default function GovOverviewPage() {
  const { t } = useTranslation();
  const { project, projectId, isLoading, isError } = useCurrentProject();

  const sources = useQuery({
    queryKey: ["gov-sources", projectId],
    queryFn: () => listSources(projectId!),
    enabled: projectId !== null,
  });
  const batches = useQuery({
    queryKey: ["gov-batches", projectId],
    queryFn: () => listBatches(projectId!),
    enabled: projectId !== null,
  });
  const golden = useQuery({
    queryKey: ["gov-golden", projectId],
    queryFn: () => listGoldenSets(projectId!),
    enabled: projectId !== null,
  });
  const ruleSets = useQuery({
    queryKey: ["gov-rules", projectId],
    queryFn: () => listRuleSets(projectId!),
    enabled: projectId !== null,
  });
  const evalRuns = useQuery({
    queryKey: ["gov-evals", projectId],
    queryFn: () => listEvalRuns(projectId!),
    enabled: projectId !== null,
  });

  const query = projectId ? `?project=${projectId}` : "";
  const pendingReview = (batches.data?.items ?? []).filter((batch) =>
    ["staged", "review_pending"].includes(batch.status),
  );
  const latestGolden = golden.data?.items?.[0];
  const activeRules = (ruleSets.data?.items ?? []).find((set) => set.status === "active");
  const proposedRules = (ruleSets.data?.items ?? []).find((set) => set.status === "proposed");
  const latestEval = evalRuns.data?.items?.[0];

  return (
    <div className="space-y-6">
      <section className="flex flex-wrap items-start justify-between gap-4">
        <div className="space-y-2">
          <h1 className="text-2xl font-semibold tracking-tight">{t("gov.overview.title")}</h1>
          <p className="text-muted-foreground max-w-2xl">{t("gov.overview.description")}</p>
        </div>
        <ProjectPicker />
      </section>

      {isError ? (
        <p className="text-destructive flex items-center gap-2 text-sm">
          <AlertCircleIcon className="size-4" />
          {t("gov.overview.loadFailed")}
        </p>
      ) : isLoading ? (
        <p className="text-muted-foreground text-sm">{t("gov.common.loading")}</p>
      ) : !project ? (
        <p className="text-muted-foreground text-sm">{t("gov.overview.noProject")}</p>
      ) : (
        <>
          <Card>
            <CardHeader>
              <CardTitle className="flex flex-wrap items-center gap-3">
                {project.name}
                <StatusBadge status={project.status} />
              </CardTitle>
              <CardDescription>{project.description}</CardDescription>
            </CardHeader>
            <CardContent className="text-muted-foreground grid gap-2 text-sm sm:grid-cols-3">
              <div>
                {t("gov.common.approvalMode")}: {t(`gov.approvalMode.${project.approval_mode}`)}
              </div>
              <div>
                {t("gov.overview.collection")}:{" "}
                <span className="font-mono text-xs">{project.collection_id}</span>
              </div>
              <div>
                {t("gov.overview.sources")}: {sources.data?.items.length ?? "…"}
              </div>
            </CardContent>
          </Card>

          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
            <Card>
              <CardHeader>
                <CardTitle className="flex items-center gap-2">
                  <GitBranchIcon className="size-5" />
                  {t("gov.overview.rulesCard")}
                </CardTitle>
                <CardDescription>{t("gov.overview.rulesCardDescription")}</CardDescription>
              </CardHeader>
              <CardContent className="space-y-2 text-sm">
                <div className="flex items-center gap-2">
                  {activeRules ? (
                    <>
                      <StatusBadge status="active" />
                      <span>
                        {t("gov.rules.version")} {activeRules.version} · {activeRules.rules.length}{" "}
                        {t("gov.rules.rulesCount")}
                      </span>
                    </>
                  ) : proposedRules ? (
                    <>
                      <StatusBadge status="proposed" />
                      <span>{t("gov.overview.rulesWaitingGate")}</span>
                    </>
                  ) : (
                    <span className="text-muted-foreground">{t("gov.overview.rulesNone")}</span>
                  )}
                </div>
                <Button asChild variant="outline" size="sm">
                  <Link to={`/gov/rules${query}`}>{t("gov.overview.open")}</Link>
                </Button>
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle className="flex items-center gap-2">
                  <DatabaseIcon className="size-5" />
                  {t("gov.overview.ingestCard")}
                </CardTitle>
                <CardDescription>{t("gov.overview.ingestCardDescription")}</CardDescription>
              </CardHeader>
              <CardContent className="space-y-2 text-sm">
                <div className="flex flex-wrap items-center gap-2">
                  {batches.data?.items?.[0] ? (
                    <>
                      <StatusBadge status={batches.data.items[0].status} />
                      <span className="text-muted-foreground text-xs">
                        {batches.data.items[0].created_at.slice(0, 19).replace("T", " ")}
                      </span>
                    </>
                  ) : (
                    <span className="text-muted-foreground">{t("gov.overview.batchesNone")}</span>
                  )}
                </div>
                <p>
                  {t("gov.overview.pendingReview", { count: pendingReview.length })}
                </p>
                <div className="flex flex-wrap gap-2">
                  <Button asChild variant="outline" size="sm">
                    <Link to={`/gov/sources${query}`}>{t("gov.overview.open")}</Link>
                  </Button>
                  {pendingReview.length > 0 ? (
                    <Button asChild size="sm">
                      <Link to={`/gov/approvals${query}`}>
                        {t("gov.overview.reviewNow", { count: pendingReview.length })}
                      </Link>
                    </Button>
                  ) : null}
                </div>
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle className="flex items-center gap-2">
                  <ScrollTextIcon className="size-5" />
                  {t("gov.overview.goldenCard")}
                </CardTitle>
                <CardDescription>{t("gov.overview.goldenCardDescription")}</CardDescription>
              </CardHeader>
              <CardContent className="space-y-2 text-sm">
                {latestGolden ? (
                  <div className="flex items-center gap-2">
                    <StatusBadge status={latestGolden.status} />
                    <span>
                      {t("gov.golden.version")} {latestGolden.version} · {latestGolden.cases.length}{" "}
                      {t("gov.golden.casesCount")}
                    </span>
                  </div>
                ) : (
                  <span className="text-muted-foreground">{t("gov.overview.goldenNone")}</span>
                )}
                <Button asChild variant="outline" size="sm">
                  <Link to={`/gov/golden${query}`}>{t("gov.overview.open")}</Link>
                </Button>
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle className="flex items-center gap-2">
                  <ShieldCheckIcon className="size-5" />
                  {t("gov.overview.evalCard")}
                </CardTitle>
                <CardDescription>{t("gov.overview.evalCardDescription")}</CardDescription>
              </CardHeader>
              <CardContent className="space-y-2 text-sm">
                {latestEval ? (
                  <div className="flex flex-wrap items-center gap-2">
                    <StatusBadge status={latestEval.status} />
                    <span className="text-muted-foreground text-xs">{latestEval.summary}</span>
                  </div>
                ) : (
                  <span className="text-muted-foreground">{t("gov.overview.evalNone")}</span>
                )}
                <Button asChild variant="outline" size="sm">
                  <Link to={`/gov/evaluations${query}`}>{t("gov.overview.open")}</Link>
                </Button>
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle className="flex items-center gap-2">
                  <ClipboardCheckIcon className="size-5" />
                  {t("gov.overview.approvalsCard")}
                </CardTitle>
                <CardDescription>{t("gov.overview.approvalsCardDescription")}</CardDescription>
              </CardHeader>
              <CardContent className="space-y-2 text-sm">
                <p>
                  {t("gov.overview.pendingReview", { count: pendingReview.length })}
                </p>
                <Button asChild variant="outline" size="sm">
                  <Link to={`/gov/approvals${query}`}>{t("gov.overview.open")}</Link>
                </Button>
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle className="flex items-center gap-2">
                  <MessageSquareIcon className="size-5" />
                  {t("gov.overview.queryCard")}
                </CardTitle>
                <CardDescription>{t("gov.overview.queryCardDescription")}</CardDescription>
              </CardHeader>
              <CardContent className="space-y-2 text-sm">
                <p className={project.status === "active" ? "" : "text-muted-foreground"}>
                  {project.status === "active"
                    ? t("gov.overview.queryReady")
                    : t("gov.overview.queryNotReady")}
                </p>
                <Button asChild variant="outline" size="sm">
                  <Link to={`/gov/query${query}`}>{t("gov.overview.open")}</Link>
                </Button>
              </CardContent>
            </Card>
          </div>
        </>
      )}
    </div>
  );
}
