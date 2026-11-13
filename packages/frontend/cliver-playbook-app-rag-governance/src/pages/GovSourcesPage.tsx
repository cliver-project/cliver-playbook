import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { AlertCircleIcon, FolderSyncIcon, RefreshCwIcon } from "lucide-react";
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
import { Input } from "cliver-playbook-app-basic/components/ui/input.tsx";
import { Label } from "cliver-playbook-app-basic/components/ui/label.tsx";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "cliver-playbook-app-basic/components/ui/table.tsx";
import {
  createSource,
  getBatch,
  listBatches,
  listSources,
  triggerIngest,
} from "cliver-playbook-app-rag-governance/api/governance.ts";
import { ProjectPicker } from "cliver-playbook-app-rag-governance/components/gov/ProjectPicker.tsx";
import { StatusBadge } from "cliver-playbook-app-rag-governance/components/gov/StatusBadge.tsx";
import { useCurrentProject } from "cliver-playbook-app-rag-governance/components/gov/useProject.ts";

/**
 * Sources and their ingestion batches.
 *
 * Ingestion is a two-worlds story and the page keeps both visible: the
 * source table shows the durable inputs (the directory the corpus lives in),
 * the batch table shows what each ingest run staged and where it sits in the
 * review state machine. Triggering an ingest returns a 202 — the batch row
 * is the polling handle, so the button invalidates the batch list and the
 * table's status column is the progress bar.
 *
 * The create form offers exactly the `directory` kind: it is the demo's
 * offline path (a folder of markdown files) and the only kind whose config
 * is a plain path. Upload/http/mcp sources are created through the same API
 * by a project that needs them.
 */
export default function GovSourcesPage() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const { projectId } = useCurrentProject();

  const sources = useQuery({
    queryKey: ["gov-sources", projectId],
    queryFn: () => listSources(projectId!),
    enabled: projectId !== null,
  });
  const batches = useQuery({
    queryKey: ["gov-batches", projectId],
    queryFn: () => listBatches(projectId!),
    enabled: projectId !== null,
    // Batches move through the state machine in the background (the worker
    // polls at ~1s); a short poll keeps the table honest during a demo
    // without a manual refresh gesture.
    refetchInterval: 5000,
  });

  const [newPath, setNewPath] = useState("");

  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: ["gov-sources", projectId] });
    void queryClient.invalidateQueries({ queryKey: ["gov-batches", projectId] });
    void queryClient.invalidateQueries({ queryKey: ["gov-projects"] });
  };

  const create = useMutation({
    mutationFn: () => createSource(projectId!, { kind: "directory", config: { path: newPath } }),
    onSuccess: () => {
      toast.success(t("gov.sources.createdToast"));
      setNewPath("");
      invalidate();
    },
    onError: (error) => toast.error(apiErrorMessage(error)),
  });

  const ingest = useMutation({
    mutationFn: (sourceId: string) => triggerIngest(sourceId),
    onSuccess: (data) => {
      toast.success(t("gov.sources.ingestAcceptedToast"));
      invalidate();
      // The batch id is in hand: watch it until it leaves queue/running so
      // the presenter sees "staged" land without touching anything.
      const batchId = data.batch_id;
      const poll = window.setInterval(async () => {
        try {
          const batch = await getBatch(batchId);
          if (!["queued", "running"].includes(batch.status)) {
            window.clearInterval(poll);
            void queryClient.invalidateQueries({ queryKey: ["gov-batches", projectId] });
            toast.success(t("gov.sources.batchSettledToast", { status: batch.status }));
          }
        } catch {
          window.clearInterval(poll);
        }
      }, 2000);
    },
    onError: (error) => toast.error(apiErrorMessage(error)),
  });

  return (
    <div className="space-y-6">
      <section className="flex flex-wrap items-start justify-between gap-4">
        <div className="space-y-2">
          <h1 className="text-2xl font-semibold tracking-tight">{t("gov.sources.title")}</h1>
          <p className="text-muted-foreground max-w-2xl">{t("gov.sources.description")}</p>
        </div>
        <ProjectPicker />
      </section>

      <Card>
        <CardHeader>
          <CardTitle>{t("gov.sources.createTitle")}</CardTitle>
          <CardDescription>{t("gov.sources.createDescription")}</CardDescription>
        </CardHeader>
        <CardContent className="flex flex-wrap items-end gap-3">
          <div className="min-w-72 flex-1 space-y-1.5">
            <Label htmlFor="gov-source-path">{t("gov.sources.pathLabel")}</Label>
            <Input
              id="gov-source-path"
              value={newPath}
              onChange={(event) => setNewPath(event.target.value)}
              placeholder={t("gov.sources.pathPlaceholder")}
            />
          </div>
          <Button onClick={() => create.mutate()} disabled={!projectId || !newPath.trim() || create.isPending}>
            {create.isPending ? t("gov.sources.creating") : t("gov.sources.create")}
          </Button>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>{t("gov.sources.listTitle")}</CardTitle>
        </CardHeader>
        <CardContent>
          {sources.isError ? (
            <p className="text-destructive flex items-center gap-2 text-sm">
              <AlertCircleIcon className="size-4" />
              {t("gov.sources.loadFailed")} ({apiErrorMessage(sources.error)})
            </p>
          ) : (sources.data?.items ?? []).length === 0 ? (
            <p className="text-muted-foreground text-sm">{t("gov.sources.empty")}</p>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>{t("gov.sources.kind")}</TableHead>
                  <TableHead>{t("gov.sources.config")}</TableHead>
                  <TableHead>{t("gov.sources.lastRun")}</TableHead>
                  <TableHead className="text-right">{t("gov.common.actions")}</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {(sources.data?.items ?? []).map((source) => (
                  <TableRow key={source.id}>
                    <TableCell className="font-mono text-xs">{source.kind}</TableCell>
                    <TableCell className="max-w-96 truncate font-mono text-xs">
                      {String(source.config.path ?? JSON.stringify(source.config))}
                    </TableCell>
                    <TableCell className="text-muted-foreground text-xs">
                      {source.last_run_at?.slice(0, 19).replace("T", " ") ?? "—"}
                    </TableCell>
                    <TableCell className="text-right">
                      <Button
                        size="sm"
                        variant="outline"
                        onClick={() => ingest.mutate(source.id)}
                        disabled={ingest.isPending}
                      >
                        <FolderSyncIcon className="size-4" />
                        {ingest.isPending ? t("gov.sources.ingesting") : t("gov.sources.ingest")}
                      </Button>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <RefreshCwIcon className="size-5" />
            {t("gov.sources.batchesTitle")}
          </CardTitle>
          <CardDescription>{t("gov.sources.batchesDescription")}</CardDescription>
        </CardHeader>
        <CardContent>
          {(batches.data?.items ?? []).length === 0 ? (
            <p className="text-muted-foreground text-sm">{t("gov.sources.batchesEmpty")}</p>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>{t("gov.sources.batch")}</TableHead>
                  <TableHead>{t("gov.common.status")}</TableHead>
                  <TableHead>{t("gov.sources.documents")}</TableHead>
                  <TableHead>{t("gov.sources.chunks")}</TableHead>
                  <TableHead>{t("gov.common.updated")}</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {(batches.data?.items ?? []).map((batch) => (
                  <TableRow key={batch.id}>
                    <TableCell className="font-mono text-xs">{batch.id.slice(0, 8)}</TableCell>
                    <TableCell>
                      <StatusBadge status={batch.status} />
                    </TableCell>
                    <TableCell>{batch.stats?.documents ?? "—"}</TableCell>
                    <TableCell>{batch.stats?.chunks ?? "—"}</TableCell>
                    <TableCell className="text-muted-foreground text-xs">
                      {batch.updated_at.slice(0, 19).replace("T", " ")}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
