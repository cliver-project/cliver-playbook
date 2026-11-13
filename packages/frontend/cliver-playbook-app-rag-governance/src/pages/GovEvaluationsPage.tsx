import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { AlertCircleIcon, PlayIcon } from "lucide-react";
import { toast } from "sonner";

import { apiErrorMessage } from "cliver-playbook-app-basic/api/client.ts";
import { Badge } from "cliver-playbook-app-basic/components/ui/badge.tsx";
import { Button } from "cliver-playbook-app-basic/components/ui/button.tsx";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "cliver-playbook-app-basic/components/ui/card.tsx";
import { Label } from "cliver-playbook-app-basic/components/ui/label.tsx";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "cliver-playbook-app-basic/components/ui/select.tsx";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "cliver-playbook-app-basic/components/ui/table.tsx";
import {
  getEvalRun,
  listBatches,
  listEvalRuns,
  listGoldenSets,
  startEvalRun,
} from "cliver-playbook-app-rag-governance/api/governance.ts";
import { ProjectPicker } from "cliver-playbook-app-rag-governance/components/gov/ProjectPicker.tsx";
import { StatusBadge } from "cliver-playbook-app-rag-governance/components/gov/StatusBadge.tsx";
import { useCurrentProject } from "cliver-playbook-app-rag-governance/components/gov/useProject.ts";

/**
 * Evaluation runs: where change earns the right to ship.
 *
 * A run replays a confirmed golden set against the current knowledge base
 * and rules; its row is immutable history with pass/fail, the aggregate
 * metrics and the per-case verdicts. The page pairs the run list with the
 * runner: pick the confirmed set, pick the stage (baseline for "prove the
 * corpus", change for "prove my edit"), and the 202 lands as a run whose
 * status column fills itself in — queued, running, then the verdict.
 *
 * The numbers a presenter cares about are the threshold metrics
 * (intent.pass_rate, retrieval.recall, tool routing, numeric facts): they
 * are rendered as badges so a red one is impossible to miss mid-demo.
 */
const METRIC_KEYS = [
  "intent.pass_rate",
  "retrieval.recall",
  "tool-routing.routing_accuracy",
  "groundedness.numeric_facts",
];

export default function GovEvaluationsPage() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const { project, projectId } = useCurrentProject();
  // The project's own thresholds decide red vs green: the badges must judge
  // by the bar this project set, not a hardcoded 1.0.
  const thresholds = (project?.config?.thresholds ?? {}) as Record<string, number>;

  const runs = useQuery({
    queryKey: ["gov-evals", projectId],
    queryFn: () => listEvalRuns(projectId!),
    enabled: projectId !== null,
    refetchInterval: 5000,
  });
  const goldenSets = useQuery({
    queryKey: ["gov-golden", projectId],
    queryFn: () => listGoldenSets(projectId!),
    enabled: projectId !== null,
  });
  const batches = useQuery({
    queryKey: ["gov-batches", projectId],
    queryFn: () => listBatches(projectId!),
    enabled: projectId !== null,
  });

  const confirmed = (goldenSets.data?.items ?? []).filter((set) => set.status === "confirmed");
  const stagedBatches = (batches.data?.items ?? []).filter((batch) =>
    ["staged", "review_pending"].includes(batch.status),
  );

  const [selectedId, setSelectedId] = useState<string | null>(null);
  const selected = selectedId ? (runs.data?.items ?? []).find((r) => r.id === selectedId) ?? null : (runs.data?.items ?? [])[0] ?? null;

  const detail = useQuery({
    queryKey: ["gov-eval-detail", selected?.id],
    queryFn: () => getEvalRun(selected!.id),
    enabled: selected !== null,
  });

  const [goldenSetId, setGoldenSetId] = useState<string | null>(null);
  const [stage, setStage] = useState<"baseline" | "change">("baseline");
  // Optional evidence link: the run id is recorded on the batch and is what
  // lets the approval gate verify the hard gates.
  const [evidenceBatchId, setEvidenceBatchId] = useState<string | null>(null);

  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: ["gov-evals", projectId] });
    void queryClient.invalidateQueries({ queryKey: ["gov-projects"] });
  };

  const start = useMutation({
    mutationFn: () =>
      startEvalRun(projectId!, {
        golden_set_id: goldenSetId!,
        stage,
        ...(evidenceBatchId ? { batch_id: evidenceBatchId } : {}),
      }),
    onSuccess: () => {
      toast.success(t("gov.evals.startedToast"));
      invalidate();
    },
    onError: (error) => toast.error(apiErrorMessage(error)),
  });

  const metricTone = (key: string, value: number) => {
    const bar = thresholds[key] ?? 1.0;
    return value >= bar ? "default" : "destructive";
  };

  return (
    <div className="space-y-6">
      <section className="flex flex-wrap items-start justify-between gap-4">
        <div className="space-y-2">
          <h1 className="text-2xl font-semibold tracking-tight">{t("gov.evals.title")}</h1>
          <p className="text-muted-foreground max-w-2xl">{t("gov.evals.description")}</p>
        </div>
        <ProjectPicker />
      </section>

      <Card>
        <CardHeader>
          <CardTitle>{t("gov.evals.startTitle")}</CardTitle>
          <CardDescription>{t("gov.evals.startDescription")}</CardDescription>
        </CardHeader>
        <CardContent className="flex flex-wrap items-end gap-3">
          <div className="space-y-1.5">
            <Label>{t("gov.evals.goldenSet")}</Label>
            <Select
              value={goldenSetId ?? undefined}
              onValueChange={setGoldenSetId}
              disabled={confirmed.length === 0}
            >
              <SelectTrigger className="w-72">
                <SelectValue
                  placeholder={
                    confirmed.length === 0 ? t("gov.evals.noConfirmedSets") : t("gov.evals.pickSet")
                  }
                />
              </SelectTrigger>
              <SelectContent>
                {confirmed.map((set) => (
                  <SelectItem key={set.id} value={set.id}>
                    v{set.version} · {set.cases.length} {t("gov.golden.casesCount")}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="space-y-1.5">
            <Label>{t("gov.evals.stage")}</Label>
            <Select value={stage} onValueChange={(value) => setStage(value as "baseline" | "change")}>
              <SelectTrigger className="w-44">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="baseline">{t("gov.evals.stageBaseline")}</SelectItem>
                <SelectItem value="change">{t("gov.evals.stageChange")}</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <div className="space-y-1.5">
            <Label>{t("gov.evals.evidenceBatch")}</Label>
            <Select
              value={evidenceBatchId ?? "none"}
              onValueChange={(value) => setEvidenceBatchId(value === "none" ? null : value)}
              disabled={stagedBatches.length === 0}
            >
              <SelectTrigger className="w-64">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="none">{t("gov.evals.noEvidenceBatch")}</SelectItem>
                {stagedBatches.map((batch) => (
                  <SelectItem key={batch.id} value={batch.id}>
                    {batch.id.slice(0, 8)} · {batch.stats?.documents ?? 0}{" "}
                    {t("gov.sources.documents")}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <Button onClick={() => start.mutate()} disabled={!projectId || !goldenSetId || start.isPending}>
            <PlayIcon className="size-4" />
            {start.isPending ? t("gov.evals.starting") : t("gov.evals.start")}
          </Button>
        </CardContent>
      </Card>

      {runs.isError ? (
        <p className="text-destructive flex items-center gap-2 text-sm">
          <AlertCircleIcon className="size-4" />
          {t("gov.evals.loadFailed")} ({apiErrorMessage(runs.error)})
        </p>
      ) : (runs.data?.items ?? []).length === 0 ? (
        <p className="text-muted-foreground text-sm">{t("gov.evals.empty")}</p>
      ) : (
        <Card>
          <CardHeader>
            <CardTitle>{t("gov.evals.runsTitle")}</CardTitle>
          </CardHeader>
          <CardContent>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>{t("gov.evals.run")}</TableHead>
                  <TableHead>{t("gov.evals.stage")}</TableHead>
                  <TableHead>{t("gov.common.status")}</TableHead>
                  <TableHead>{t("gov.evals.summary")}</TableHead>
                  <TableHead>{t("gov.common.updated")}</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {(runs.data?.items ?? []).map((run) => (
                  <TableRow
                    key={run.id}
                    className={`${selected?.id === run.id ? "bg-muted/50 " : ""}cursor-pointer`}
                    onClick={() => setSelectedId(run.id)}
                  >
                    <TableCell className="font-mono text-xs">{run.id.slice(0, 8)}</TableCell>
                    <TableCell className="text-xs">{run.stage}</TableCell>
                    <TableCell>
                      <StatusBadge status={run.status} />
                    </TableCell>
                    <TableCell className="max-w-72 truncate text-muted-foreground text-xs">
                      {run.summary || "—"}
                    </TableCell>
                    <TableCell className="text-muted-foreground text-xs">
                      {(run.finished_at ?? run.created_at).slice(0, 19).replace("T", " ")}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      )}

      {detail.data ? (
        <Card>
          <CardHeader>
            <CardTitle className="flex flex-wrap items-center gap-3">
              {t("gov.evals.detailTitle")} · {detail.data.id.slice(0, 8)}
              <StatusBadge status={detail.data.status} />
            </CardTitle>
            <CardDescription>{detail.data.summary}</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="flex flex-wrap gap-2">
              {METRIC_KEYS.map((key) => {
                const value = detail.data.metrics[key];
                return value === undefined ? null : (
                  <Badge key={key} variant={metricTone(key, value)}>
                    {key} = {value}
                  </Badge>
                );
              })}
              {Object.entries(detail.data.metrics)
                .filter(([key]) => !METRIC_KEYS.includes(key))
                .map(([key, value]) => (
                  <Badge key={key} variant="outline">
                    {key} = {value}
                  </Badge>
                ))}
            </div>
            {detail.data.cases.length > 0 ? (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>{t("gov.golden.case")}</TableHead>
                    <TableHead>{t("gov.evals.passed")}</TableHead>
                    <TableHead>{t("gov.evals.notes")}</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {detail.data.cases.map((case_) => (
                    <TableRow key={case_.case_id}>
                      <TableCell className="font-mono text-xs">{case_.case_id}</TableCell>
                      <TableCell>
                        <StatusBadge status={case_.passed ? "passed" : "failed"} />
                      </TableCell>
                      <TableCell className="max-w-96 truncate text-muted-foreground text-xs">
                        {String(
                          (case_.details as { notes?: string })?.notes ??
                            (case_.details as { reason?: string })?.reason ??
                            "",
                        )}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            ) : null}
          </CardContent>
        </Card>
      ) : null}
    </div>
  );
}
