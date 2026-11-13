import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { AlertCircleIcon, CheckIcon, XIcon } from "lucide-react";
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
import { Label } from "cliver-playbook-app-basic/components/ui/label.tsx";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "cliver-playbook-app-basic/components/ui/table.tsx";
import { Textarea } from "cliver-playbook-app-basic/components/ui/textarea.tsx";
import {
  decideApproval,
  listApprovals,
  listBatches,
  listStaged,
  type Batch,
} from "cliver-playbook-app-rag-governance/api/governance.ts";
import { ProjectPicker } from "cliver-playbook-app-rag-governance/components/gov/ProjectPicker.tsx";
import { StatusBadge } from "cliver-playbook-app-rag-governance/components/gov/StatusBadge.tsx";
import { useCurrentProject } from "cliver-playbook-app-rag-governance/components/gov/useProject.ts";

/**
 * The approval gate.
 *
 * Nothing staged becomes searchable without a decision recorded here, and
 * the page is built around that fact: the queue is the batches sitting in
 * review, selecting one loads its staged documents — the exact rows approval
 * would publish, readable only with `staged:read` — and the decision box
 * writes an append-only approval with a comment. The server may still refuse
 * (an evaluation hard gate); the toast surfaces that reason verbatim instead
 * of pretending the click itself is the gate.
 */
export default function GovApprovalsPage() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const { projectId } = useCurrentProject();

  const batches = useQuery({
    queryKey: ["gov-batches", projectId],
    queryFn: () => listBatches(projectId!),
    enabled: projectId !== null,
    refetchInterval: 5000,
  });

  const queue = (batches.data?.items ?? []).filter((batch) =>
    ["staged", "review_pending"].includes(batch.status),
  );
  const settled = (batches.data?.items ?? []).filter(
    (batch) => !["staged", "review_pending"].includes(batch.status),
  );

  const [selected, setSelected] = useState<Batch | null>(null);
  const current = selected ? (batches.data?.items ?? []).find((b) => b.id === selected.id) ?? selected : null;

  const staged = useQuery({
    queryKey: ["gov-staged", current?.id],
    queryFn: () => listStaged(current!.id),
    enabled: current !== null,
  });
  const history = useQuery({
    queryKey: ["gov-approvals", current?.id],
    queryFn: () => listApprovals(current!.id),
    enabled: current !== null,
  });

  const [comment, setComment] = useState("");

  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: ["gov-batches", projectId] });
    void queryClient.invalidateQueries({ queryKey: ["gov-projects"] });
  };

  const decide = useMutation({
    mutationFn: (decision: "approve" | "reject") =>
      decideApproval(current!.id, decision, comment),
    onSuccess: (data, decision) => {
      toast.success(
        decision === "approve"
          ? t("gov.approvals.approvedToast", { status: data.batch.status })
          : t("gov.approvals.rejectedToast"),
      );
      setComment("");
      invalidate();
    },
    onError: (error) => toast.error(apiErrorMessage(error)),
  });

  return (
    <div className="space-y-6">
      <section className="flex flex-wrap items-start justify-between gap-4">
        <div className="space-y-2">
          <h1 className="text-2xl font-semibold tracking-tight">{t("gov.approvals.title")}</h1>
          <p className="text-muted-foreground max-w-2xl">{t("gov.approvals.description")}</p>
        </div>
        <ProjectPicker />
      </section>

      {batches.isError ? (
        <p className="text-destructive flex items-center gap-2 text-sm">
          <AlertCircleIcon className="size-4" />
          {t("gov.approvals.loadFailed")} ({apiErrorMessage(batches.error)})
        </p>
      ) : queue.length === 0 ? (
        <p className="text-muted-foreground text-sm">{t("gov.approvals.queueEmpty")}</p>
      ) : (
        <Card>
          <CardHeader>
            <CardTitle>{t("gov.approvals.queueTitle", { count: queue.length })}</CardTitle>
            <CardDescription>{t("gov.approvals.queueDescription")}</CardDescription>
          </CardHeader>
          <CardContent>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>{t("gov.sources.batch")}</TableHead>
                  <TableHead>{t("gov.common.status")}</TableHead>
                  <TableHead>{t("gov.sources.documents")}</TableHead>
                  <TableHead>{t("gov.sources.chunks")}</TableHead>
                  <TableHead>{t("gov.common.updated")}</TableHead>
                  <TableHead className="text-right">{t("gov.common.actions")}</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {queue.map((batch) => (
                  <TableRow
                    key={batch.id}
                    className={current?.id === batch.id ? "bg-muted/50" : ""}
                  >
                    <TableCell className="font-mono text-xs">{batch.id.slice(0, 8)}</TableCell>
                    <TableCell>
                      <StatusBadge status={batch.status} />
                    </TableCell>
                    <TableCell>{batch.stats?.documents ?? "—"}</TableCell>
                    <TableCell>{batch.stats?.chunks ?? "—"}</TableCell>
                    <TableCell className="text-muted-foreground text-xs">
                      {batch.updated_at.slice(0, 19).replace("T", " ")}
                    </TableCell>
                    <TableCell className="text-right">
                      <Button size="sm" variant="outline" onClick={() => setSelected(batch)}>
                        {t("gov.approvals.review")}
                      </Button>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      )}

      {current ? (
        <>
          <Card>
            <CardHeader>
              <CardTitle>
                {t("gov.approvals.stagedTitle")} · {current.id.slice(0, 8)}
              </CardTitle>
              <CardDescription>{t("gov.approvals.stagedDescription")}</CardDescription>
            </CardHeader>
            <CardContent>
              {staged.isLoading ? (
                <p className="text-muted-foreground text-sm">{t("gov.common.loading")}</p>
              ) : (staged.data?.items ?? []).length === 0 ? (
                <p className="text-muted-foreground text-sm">{t("gov.approvals.stagedEmpty")}</p>
              ) : (
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>{t("gov.approvals.logicalId")}</TableHead>
                      <TableHead>{t("gov.approvals.title_")}</TableHead>
                      <TableHead>{t("gov.approvals.classification")}</TableHead>
                      <TableHead className="text-right">{t("gov.sources.chunks")}</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {(staged.data?.items ?? []).map((doc) => (
                      <TableRow key={doc.id}>
                        <TableCell className="font-mono text-xs">{doc.logical_id ?? "—"}</TableCell>
                        <TableCell>{doc.title}</TableCell>
                        <TableCell>L{doc.classification ?? 0}</TableCell>
                        <TableCell className="text-right">{doc.chunk_count}</TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>{t("gov.approvals.decisionTitle")}</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="space-y-1.5">
                <Label htmlFor="gov-approval-comment">{t("gov.approvals.commentLabel")}</Label>
                <Textarea
                  id="gov-approval-comment"
                  rows={3}
                  value={comment}
                  onChange={(event) => setComment(event.target.value)}
                  placeholder={t("gov.approvals.commentPlaceholder")}
                />
              </div>
              <div className="flex flex-wrap gap-3">
                <Button
                  onClick={() => decide.mutate("approve")}
                  disabled={decide.isPending}
                >
                  <CheckIcon className="size-4" />
                  {decide.isPending ? t("gov.approvals.deciding") : t("gov.approvals.approve")}
                </Button>
                <Button
                  variant="destructive"
                  onClick={() => decide.mutate("reject")}
                  disabled={decide.isPending}
                >
                  <XIcon className="size-4" />
                  {t("gov.approvals.reject")}
                </Button>
              </div>
              {(history.data?.items ?? []).length > 0 ? (
                <div className="space-y-1 text-sm">
                  <p className="font-medium">{t("gov.approvals.history")}</p>
                  {(history.data?.items ?? []).map((approval) => (
                    <p key={approval.id} className="text-muted-foreground text-xs">
                      {approval.created_at.slice(0, 19).replace("T", " ")} ·{" "}
                      {approval.decision} · {approval.actor_id}
                      {approval.comment ? ` — ${approval.comment}` : ""}
                    </p>
                  ))}
                </div>
              ) : null}
            </CardContent>
          </Card>
        </>
      ) : null}

      {settled.length > 0 ? (
        <Card>
          <CardHeader>
            <CardTitle>{t("gov.approvals.settledTitle")}</CardTitle>
          </CardHeader>
          <CardContent>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>{t("gov.sources.batch")}</TableHead>
                  <TableHead>{t("gov.common.status")}</TableHead>
                  <TableHead>{t("gov.approvals.decidedBy")}</TableHead>
                  <TableHead>{t("gov.common.updated")}</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {settled.map((batch) => (
                  <TableRow key={batch.id}>
                    <TableCell className="font-mono text-xs">{batch.id.slice(0, 8)}</TableCell>
                    <TableCell>
                      <StatusBadge status={batch.status} />
                    </TableCell>
                    <TableCell className="text-xs">{batch.approved_by ?? "—"}</TableCell>
                    <TableCell className="text-muted-foreground text-xs">
                      {batch.updated_at.slice(0, 19).replace("T", " ")}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      ) : null}
    </div>
  );
}
