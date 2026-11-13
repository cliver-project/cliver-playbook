import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { AlertCircleIcon, CheckCheckIcon, GitForkIcon, SparklesIcon } from "lucide-react";
import { toast } from "sonner";

import { apiErrorMessage } from "cliver-playbook-app-basic/api/client.ts";
import { Button } from "cliver-playbook-app-basic/components/ui/button.tsx";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "cliver-playbook-app-basic/components/ui/card.tsx";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "cliver-playbook-app-basic/components/ui/table.tsx";
import {
  confirmGoldenSet,
  forkGoldenSet,
  generateGolden,
  importGolden,
  listGoldenSets,
} from "cliver-playbook-app-rag-governance/api/governance.ts";
import {
  JsonTextArea,
  parseJsonLinesText,
} from "cliver-playbook-app-rag-governance/components/gov/JsonTextArea.tsx";
import { ProjectPicker } from "cliver-playbook-app-rag-governance/components/gov/ProjectPicker.tsx";
import { StatusBadge } from "cliver-playbook-app-rag-governance/components/gov/StatusBadge.tsx";
import { useCurrentProject } from "cliver-playbook-app-rag-governance/components/gov/useProject.ts";

/**
 * Golden sets: the frozen yardstick every change is measured against.
 *
 * The table is the version history — candidate / confirmed, who confirmed —
 * and the selected set's cases show what a case IS: a question, the expected
 * intent and strategy, the sources that must be cited, the numeric facts the
 * answer must contain. Confirmed sets are immutable; the fork button starts
 * the next version instead of editing history, which is exactly the story a
 * presenter tells here.
 *
 * Import accepts the same JSONL the export endpoint produces, so a set can
 * round-trip through review outside the UI. LLM generation is offered too:
 * it enqueues a candidate set (a 202 — the set appears in the list when the
 * worker finishes), which a human then confirms. The machine proposes, the
 * human disposes; that division is the product.
 */
export default function GovGoldenPage() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const { projectId } = useCurrentProject();

  const sets = useQuery({
    queryKey: ["gov-golden", projectId],
    queryFn: () => listGoldenSets(projectId!),
    enabled: projectId !== null,
    refetchInterval: 5000,
  });

  const items = sets.data?.items ?? [];
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const selected = items.find((set) => set.id === selectedId) ?? items[0] ?? null;

  const [importText, setImportText] = useState("");
  const importParsed = parseJsonLinesText(importText);

  const invalidate = () =>
    void queryClient.invalidateQueries({ queryKey: ["gov-golden", projectId] });

  const confirm = useMutation({
    mutationFn: () => confirmGoldenSet(selected!.id),
    onSuccess: () => {
      toast.success(t("gov.golden.confirmedToast"));
      invalidate();
    },
    onError: (error) => toast.error(apiErrorMessage(error)),
  });

  const fork = useMutation({
    mutationFn: () => forkGoldenSet(selected!.id),
    onSuccess: (data) => {
      toast.success(t("gov.golden.forkedToast", { version: data.version }));
      setSelectedId(data.id);
      invalidate();
    },
    onError: (error) => toast.error(apiErrorMessage(error)),
  });

  const generate = useMutation({
    mutationFn: () => generateGolden(projectId!, ""),
    onSuccess: () => {
      toast.success(t("gov.golden.generateAcceptedToast"));
      invalidate();
    },
    onError: (error) => toast.error(apiErrorMessage(error)),
  });

  const import_ = useMutation({
    // JSONL: one case object per line; empty lines are the exporter's
    // trailing newline and are dropped before the shape check.
    mutationFn: () => {
      // The API takes the JSONL text verbatim; the server parses and
      // validates each line against the GoldenCase schema.
      return importGolden(projectId!, importText);
    },
    onSuccess: (data) => {
      toast.success(t("gov.golden.importedToast", { count: data.cases.length }));
      setImportText("");
      setSelectedId(data.id);
      invalidate();
    },
    onError: (error) => toast.error(apiErrorMessage(error)),
  });

  // JSON Lines: at least one well-formed line and no malformed one.
  const importValid = "error" in importParsed === false && importParsed.lineCount > 0;

  return (
    <div className="space-y-6">
      <section className="flex flex-wrap items-start justify-between gap-4">
        <div className="space-y-2">
          <h1 className="text-2xl font-semibold tracking-tight">{t("gov.golden.title")}</h1>
          <p className="text-muted-foreground max-w-2xl">{t("gov.golden.description")}</p>
        </div>
        <ProjectPicker />
      </section>

      {sets.isError ? (
        <p className="text-destructive flex items-center gap-2 text-sm">
          <AlertCircleIcon className="size-4" />
          {t("gov.golden.loadFailed")} ({apiErrorMessage(sets.error)})
        </p>
      ) : items.length === 0 ? (
        <p className="text-muted-foreground text-sm">{t("gov.golden.empty")}</p>
      ) : (
        <Card>
          <CardHeader>
            <CardTitle>{t("gov.golden.setsTitle")}</CardTitle>
            <CardDescription>{t("gov.golden.setsDescription")}</CardDescription>
          </CardHeader>
          <CardContent>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>{t("gov.golden.version")}</TableHead>
                  <TableHead>{t("gov.common.status")}</TableHead>
                  <TableHead>{t("gov.golden.source")}</TableHead>
                  <TableHead>{t("gov.golden.confirmedBy")}</TableHead>
                  <TableHead className="text-right">{t("gov.golden.casesCount")}</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {items.map((set) => (
                  <TableRow
                    key={set.id}
                    className={selected?.id === set.id ? "bg-muted/50 cursor-pointer" : "cursor-pointer"}
                    onClick={() => setSelectedId(set.id)}
                  >
                    <TableCell className="font-mono">v{set.version}</TableCell>
                    <TableCell>
                      <StatusBadge status={set.status} />
                    </TableCell>
                    <TableCell className="text-xs">{set.source}</TableCell>
                    <TableCell className="text-xs">{set.confirmed_by ?? "—"}</TableCell>
                    <TableCell className="text-right">{set.cases.length}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      )}

      {selected ? (
        <Card>
          <CardHeader>
            <CardTitle className="flex flex-wrap items-center gap-3">
              {t("gov.golden.casesTitle")} · v{selected.version}
              <StatusBadge status={selected.status} />
            </CardTitle>
            <CardDescription>{t("gov.golden.casesDescription")}</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>{t("gov.golden.case")}</TableHead>
                  <TableHead>{t("gov.golden.question")}</TableHead>
                  <TableHead>{t("gov.rules.intent")}</TableHead>
                  <TableHead>{t("gov.rules.strategy")}</TableHead>
                  <TableHead>{t("gov.golden.clearance")}</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {selected.cases.map((case_) => (
                  <TableRow key={case_.id}>
                    <TableCell className="font-mono text-xs">{case_.id}</TableCell>
                    <TableCell className="max-w-96 truncate">{case_.question}</TableCell>
                    <TableCell className="font-mono text-xs">{case_.expected_intent}</TableCell>
                    <TableCell>
                      {case_.expected_strategy ? (
                        <StatusBadge status={case_.expected_strategy} />
                      ) : (
                        "—"
                      )}
                    </TableCell>
                    <TableCell>L{case_.run_as_clearance ?? 0}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
            <div className="flex flex-wrap gap-3">
              {selected.status === "candidate" ? (
                <Button onClick={() => confirm.mutate()} disabled={confirm.isPending}>
                  <CheckCheckIcon className="size-4" />
                  {confirm.isPending ? t("gov.golden.confirming") : t("gov.golden.confirm")}
                </Button>
              ) : null}
              <Button variant="outline" onClick={() => fork.mutate()} disabled={fork.isPending}>
                <GitForkIcon className="size-4" />
                {fork.isPending ? t("gov.golden.forking") : t("gov.golden.fork")}
              </Button>
            </div>
          </CardContent>
        </Card>
      ) : null}

      <Card>
        <CardHeader>
          <CardTitle>{t("gov.golden.importTitle")}</CardTitle>
          <CardDescription>{t("gov.golden.importDescription")}</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <JsonTextArea
            value={importText}
            onChange={setImportText}
            rows={6}
            format="jsonl"
            placeholder={'{"id": "case-0001", "question": "…", "expected_intent": "policy_question"}'}
          />
          <div className="flex flex-wrap gap-3">
            <Button
              onClick={() => import_.mutate()}
              disabled={!projectId || !importValid || import_.isPending}
            >
              {import_.isPending ? t("gov.golden.importing") : t("gov.golden.import")}
            </Button>
            <Button
              variant="outline"
              onClick={() => generate.mutate()}
              disabled={!projectId || generate.isPending}
            >
              <SparklesIcon className="size-4" />
              {generate.isPending ? t("gov.golden.generating") : t("gov.golden.generate")}
            </Button>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
