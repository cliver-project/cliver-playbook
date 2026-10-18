import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { AlertCircleIcon, FileUpIcon } from "lucide-react";
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
  fetchStageCatalog,
  indexDocument,
  listDocuments,
  uploadDocument,
  type DocumentRow,
  type UploadResponse,
} from "cliver-playbook-app-rag/api/rag.ts";
import { ChunkPreview } from "cliver-playbook-app-rag/components/rag/ChunkPreview.tsx";
import { StageSelector } from "cliver-playbook-app-rag/components/rag/StageSelector.tsx";

/**
 * Knowledge-base documents: upload, inspect the chunking, then index.
 *
 * The page walks the ingestion stages in the order the server defines them.
 * The chunker and embedder are chosen before the upload from the server's
 * stage catalog; the response is a preview with `pending` status. Only after
 * the user has seen the chunks does the Index action run the embedder and make
 * the document searchable. Keeping the two steps visible is the point — the
 * embedder is the expensive, potentially model-downloading stage, and the
 * chunk boundaries are what the user can still reason about cheaply.
 *
 * The documents table below is the server's view: status, the stages each row
 * was produced with, and the chunk count. Re-uploading the same file updates
 * the same row (document ids are content hashes), so the table stays a set of
 * current documents rather than an upload log.
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

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : apiErrorMessage(error);
}

function formatTimestamp(value: string | null): string {
  if (!value) return "—";
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString();
}

function StatusBadge({ status }: { status: string }) {
  const { t } = useTranslation();
  const label = STATUS_LABEL[status] ? t(STATUS_LABEL[status]) : status;
  return <Badge variant={STATUS_VARIANT[status] ?? "outline"}>{label}</Badge>;
}

export default function RagDocumentsPage() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();

  const catalog = useQuery({ queryKey: ["rag-stages"], queryFn: fetchStageCatalog });
  const documents = useQuery({ queryKey: ["rag-documents"], queryFn: listDocuments });

  const [file, setFile] = useState<File | null>(null);
  const [chunker, setChunker] = useState<string | null>(null);
  const [embedder, setEmbedder] = useState<string | null>(null);
  const [chunkSize, setChunkSize] = useState("");
  const [chunkOverlap, setChunkOverlap] = useState("");
  const [preview, setPreview] = useState<UploadResponse | null>(null);

  // Fall back to the server's defaults until the user overrides a stage, so
  // the form is usable before the catalog query resolves.
  const effectiveChunker = chunker ?? catalog.data?.defaults.chunker ?? "";
  const effectiveEmbedder = embedder ?? catalog.data?.defaults.embedder ?? "";

  const upload = useMutation({
    mutationFn: () => {
      if (!file) throw new Error(t("rag.documents.fileRequired"));
      return uploadDocument({
        file,
        chunker: effectiveChunker || undefined,
        embedder: effectiveEmbedder || undefined,
        chunkSize: chunkSize.trim() ? Number(chunkSize) : undefined,
        chunkOverlap: chunkOverlap.trim() ? Number(chunkOverlap) : undefined,
      });
    },
    onSuccess: (data) => {
      setPreview(data);
      void queryClient.invalidateQueries({ queryKey: ["rag-documents"] });
      toast.success(t("rag.documents.uploadedToast", { count: data.chunk_count }));
    },
    onError: (error) => toast.error(errorMessage(error)),
  });

  const index = useMutation({
    mutationFn: (documentId: string) => indexDocument(documentId),
    onSuccess: (data) => {
      setPreview((current) =>
        current ? { ...current, status: data.status, dim: data.dim } : current,
      );
      void queryClient.invalidateQueries({ queryKey: ["rag-documents"] });
      toast.success(t("rag.documents.indexedToast", { count: data.chunk_count }));
    },
    onError: (error) => toast.error(errorMessage(error)),
  });

  const rows: DocumentRow[] = documents.data?.items ?? [];

  return (
    <div className="space-y-6">
      <section className="space-y-2">
        <h1 className="text-2xl font-semibold tracking-tight">{t("rag.documents.title")}</h1>
        <p className="text-muted-foreground max-w-2xl">{t("rag.documents.description")}</p>
      </section>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <FileUpIcon className="size-5" />
            {t("rag.documents.uploadTitle")}
          </CardTitle>
          <CardDescription>{t("rag.documents.uploadDescription")}</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {catalog.isError ? (
            <p className="text-destructive flex items-center gap-2 text-sm">
              <AlertCircleIcon className="size-4" />
              {t("rag.documents.catalogFailed")} ({apiErrorMessage(catalog.error)})
            </p>
          ) : null}

          <div className="space-y-1.5">
            <Label htmlFor="rag-file">{t("rag.documents.fileLabel")}</Label>
            <Input
              id="rag-file"
              type="file"
              onChange={(event) => setFile(event.target.files?.[0] ?? null)}
            />
            <p className="text-muted-foreground text-xs">{t("rag.documents.fileHint")}</p>
          </div>

          <div className="grid gap-4 md:grid-cols-2">
            <StageSelector
              id="rag-chunker"
              label={t("rag.documents.chunkerLabel")}
              value={effectiveChunker}
              options={catalog.data?.chunkers ?? []}
              onChange={setChunker}
              disabled={upload.isPending}
              description={t("rag.documents.chunkerHint")}
            />
            <StageSelector
              id="rag-embedder"
              label={t("rag.documents.embedderLabel")}
              value={effectiveEmbedder}
              options={catalog.data?.embedders ?? []}
              onChange={setEmbedder}
              disabled={upload.isPending}
              description={t("rag.documents.embedderHint")}
            />
          </div>

          <details className="rounded-md border p-3">
            <summary className="cursor-pointer text-sm font-medium">
              {t("rag.documents.advanced")}
            </summary>
            <div className="mt-3 grid gap-4 md:grid-cols-2">
              <div className="space-y-1.5">
                <Label htmlFor="rag-chunk-size">{t("rag.documents.chunkSizeLabel")}</Label>
                <Input
                  id="rag-chunk-size"
                  type="number"
                  min={1}
                  value={chunkSize}
                  onChange={(event) => setChunkSize(event.target.value)}
                  placeholder={t("rag.documents.chunkSizePlaceholder")}
                />
                <p className="text-muted-foreground text-xs">
                  {t("rag.documents.chunkSizeHint")}
                </p>
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="rag-chunk-overlap">{t("rag.documents.chunkOverlapLabel")}</Label>
                <Input
                  id="rag-chunk-overlap"
                  type="number"
                  min={0}
                  value={chunkOverlap}
                  onChange={(event) => setChunkOverlap(event.target.value)}
                  placeholder={t("rag.documents.chunkOverlapPlaceholder")}
                />
                <p className="text-muted-foreground text-xs">
                  {t("rag.documents.chunkOverlapHint")}
                </p>
              </div>
            </div>
          </details>

          <Button
            onClick={() => upload.mutate()}
            disabled={!file || upload.isPending}
            className="w-full md:w-auto"
          >
            {upload.isPending ? t("rag.documents.previewing") : t("rag.documents.preview")}
          </Button>
        </CardContent>
      </Card>

      {preview ? (
        <Card>
          <CardHeader>
            <CardTitle className="flex flex-wrap items-center gap-2">
              {t("rag.documents.previewTitle")}
              <StatusBadge status={preview.status} />
            </CardTitle>
            <CardDescription>
              {t("rag.documents.previewDescription", {
                chunker: preview.chunker,
                embedder: preview.embedder,
                dim: preview.dim,
                count: preview.chunk_count,
              })}
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <ChunkPreview
              chunks={preview.preview_chunks}
              truncated={preview.preview_truncated}
            />
            <div className="flex flex-wrap items-center gap-3">
              <Button
                onClick={() => index.mutate(preview.document_id)}
                disabled={preview.status === "indexed" || index.isPending}
              >
                {index.isPending ? t("rag.documents.indexing") : t("rag.documents.index")}
              </Button>
              <span className="text-muted-foreground text-xs">
                {preview.status === "indexed"
                  ? t("rag.documents.alreadyIndexed")
                  : t("rag.documents.indexHint")}
              </span>
            </div>
          </CardContent>
        </Card>
      ) : null}

      <Card>
        <CardHeader>
          <CardTitle>{t("rag.documents.listTitle")}</CardTitle>
          <CardDescription>{t("rag.documents.listDescription")}</CardDescription>
        </CardHeader>
        <CardContent>
          {documents.isError ? (
            <p className="text-destructive flex items-center gap-2 text-sm">
              <AlertCircleIcon className="size-4" />
              {t("rag.documents.listFailed")} ({apiErrorMessage(documents.error)})
            </p>
          ) : rows.length === 0 ? (
            <p className="text-muted-foreground text-sm">{t("rag.documents.empty")}</p>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>{t("rag.common.document")}</TableHead>
                  <TableHead>{t("rag.common.status")}</TableHead>
                  <TableHead>{t("rag.common.chunker")}</TableHead>
                  <TableHead>{t("rag.common.embedder")}</TableHead>
                  <TableHead className="text-right">{t("rag.common.chunks")}</TableHead>
                  <TableHead>{t("rag.common.updated")}</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {rows.map((row) => (
                  <TableRow key={row.id}>
                    <TableCell>
                      <div className="font-medium">{row.title}</div>
                      {row.failure_reason ? (
                        <div className="text-destructive text-xs">{row.failure_reason}</div>
                      ) : null}
                    </TableCell>
                    <TableCell>
                      <StatusBadge status={row.status} />
                    </TableCell>
                    <TableCell className="font-mono text-xs">{row.chunker_id}</TableCell>
                    <TableCell className="font-mono text-xs">
                      {row.embedder_id} · {row.dim}d
                    </TableCell>
                    <TableCell className="text-right">{row.chunk_count}</TableCell>
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
