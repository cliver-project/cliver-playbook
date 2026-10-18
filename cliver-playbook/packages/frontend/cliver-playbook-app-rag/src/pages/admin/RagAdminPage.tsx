import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { AlertCircleIcon, RefreshCwIcon } from "lucide-react";

import { apiErrorMessage } from "cliver-playbook-app-basic/api/client.ts";
import { Badge } from "cliver-playbook-app-basic/components/ui/badge.tsx";
import { Button } from "cliver-playbook-app-basic/components/ui/button.tsx";
import {
  Card,
  CardContent,
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
import { listDocuments, type DocumentRow } from "cliver-playbook-app-rag/api/rag.ts";

/**
 * Administrator's view of the shared knowledge base.
 *
 * The RAG pages are permission-gated, but the documents themselves are shared:
 * this view is the whole corpus with the lifecycle fields an operator needs
 * when something goes wrong — the stages each row was produced with, counts,
 * versions, timestamps and the failure reason. It reads the same document
 * listing as the upload page; the route-level `rag:admin:read` gate is what
 * distinguishes the audience, while the server still enforces every call.
 */

const STATUS_VARIANT: Record<string, "secondary" | "outline" | "destructive"> = {
  indexed: "secondary",
  pending: "outline",
  failed: "destructive",
};

const STATUS_LABEL: Record<string, string> = {
  indexed: "rag.documents.statusIndexed",
  pending: "rag.documents.statusPending",
  failed: "rag.documents.statusFailed",
};

function formatTimestamp(value: string | null): string {
  if (!value) return "—";
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString();
}

function countStatus(rows: DocumentRow[], status: string): number {
  return rows.filter((row) => row.status === status).length;
}

export default function RagAdminPage() {
  const { t } = useTranslation();

  const documents = useQuery({ queryKey: ["rag-documents"], queryFn: listDocuments });
  const rows = documents.data?.items ?? [];

  return (
    <div className="space-y-6">
      <section className="space-y-2">
        <h1 className="text-2xl font-semibold tracking-tight">{t("rag.admin.title")}</h1>
        <p className="text-muted-foreground max-w-2xl">{t("rag.admin.description")}</p>
      </section>

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-muted-foreground text-sm font-medium">
              {t("rag.admin.total")}
            </CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-3xl font-semibold">{rows.length}</p>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-muted-foreground text-sm font-medium">
              {t("rag.admin.indexed")}
            </CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-3xl font-semibold">{countStatus(rows, "indexed")}</p>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-muted-foreground text-sm font-medium">
              {t("rag.admin.pending")}
            </CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-3xl font-semibold">{countStatus(rows, "pending")}</p>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-muted-foreground text-sm font-medium">
              {t("rag.admin.failed")}
            </CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-3xl font-semibold">{countStatus(rows, "failed")}</p>
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <div className="flex items-center justify-between gap-4">
            <CardTitle>{t("rag.admin.documentsTitle")}</CardTitle>
            <Button
              variant="outline"
              size="sm"
              onClick={() => void documents.refetch()}
              disabled={documents.isFetching}
            >
              <RefreshCwIcon className="size-4" />
              {t("rag.common.refresh")}
            </Button>
          </div>
        </CardHeader>
        <CardContent>
          {documents.isError ? (
            <p className="text-destructive flex items-center gap-2 text-sm">
              <AlertCircleIcon className="size-4" />
              {t("rag.admin.loadFailed")} ({apiErrorMessage(documents.error)})
            </p>
          ) : rows.length === 0 ? (
            <p className="text-muted-foreground text-sm">{t("rag.admin.empty")}</p>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>{t("rag.common.document")}</TableHead>
                  <TableHead>{t("rag.common.status")}</TableHead>
                  <TableHead>{t("rag.common.stages")}</TableHead>
                  <TableHead className="text-right">{t("rag.common.chunks")}</TableHead>
                  <TableHead className="text-right">{t("rag.common.version")}</TableHead>
                  <TableHead>{t("rag.common.updated")}</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {rows.map((row) => (
                  <TableRow key={row.id}>
                    <TableCell>
                      <div className="font-medium">{row.title}</div>
                      <div className="text-muted-foreground font-mono text-xs">{row.id}</div>
                      {row.failure_reason ? (
                        <div className="text-destructive text-xs">{row.failure_reason}</div>
                      ) : null}
                    </TableCell>
                    <TableCell>
                      <Badge variant={STATUS_VARIANT[row.status] ?? "outline"}>
                        {STATUS_LABEL[row.status] ? t(STATUS_LABEL[row.status]) : row.status}
                      </Badge>
                    </TableCell>
                    <TableCell className="font-mono text-xs">
                      {row.chunker_id} / {row.embedder_id} · {row.dim}d
                    </TableCell>
                    <TableCell className="text-right">{row.chunk_count}</TableCell>
                    <TableCell className="text-right">{row.version}</TableCell>
                    <TableCell className="text-muted-foreground text-xs">
                      {formatTimestamp(row.updated_at)}
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
