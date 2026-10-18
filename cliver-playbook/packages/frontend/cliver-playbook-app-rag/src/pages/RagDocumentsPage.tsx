import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { AlertCircleIcon, FileUpIcon, Trash2Icon } from "lucide-react";
import { toast } from "sonner";

import { apiErrorMessage } from "cliver-playbook-app-basic/api/client.ts";
import { ConfirmDialog } from "cliver-playbook-app-basic/components/ConfirmDialog.tsx";
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
  deleteDocument,
  fetchStageCatalog,
  indexDocument,
  listDocuments,
  uploadDocument,
  type DocumentRow,
  type UploadResponse,
} from "cliver-playbook-app-rag/api/rag.ts";
import { ChunkPreview } from "cliver-playbook-app-rag/components/rag/ChunkPreview.tsx";
import {
  DocumentFailureReason,
  DocumentStatusBadge,
  formatDocumentTimestamp,
} from "cliver-playbook-app-rag/components/rag/documentStatus.tsx";
import { StageSelector } from "cliver-playbook-app-rag/components/rag/StageSelector.tsx";
import { useAuth } from "cliver-playbook-app-user/components/auth/AuthContext.tsx";

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
 * The embedder may be changed *after* the preview: the index endpoint accepts
 * an override, so the selector below stays live and the preview card reports
 * the embedder that actually produced the stored vectors afterwards.
 *
 * The documents table below is the server's view: status, the stages each row
 * was produced with, and the chunk count. Re-uploading the same file updates
 * the same row (document ids are content hashes), so the table stays a set of
 * current documents rather than an upload log. Pending rows carry their own
 * Index action because a page reload would otherwise lose the way to finish
 * an upload.
 *
 * Every mutating control is hidden from read-only viewers (`hasPerm` is a
 * display gate; the server enforces `rag:documents:write` on every call).
 */

function parseWholeNumber(raw: string): number | undefined {
  const trimmed = raw.trim();
  if (!trimmed) return undefined;
  const value = Number(trimmed);
  return Number.isInteger(value) && value >= 0 ? value : undefined;
}

export default function RagDocumentsPage() {
  const { t, i18n } = useTranslation();
  const queryClient = useQueryClient();
  const { hasPerm } = useAuth();
  const canWrite = hasPerm("rag:documents:write");

  const catalog = useQuery({ queryKey: ["rag-stages"], queryFn: fetchStageCatalog });
  const documents = useQuery({ queryKey: ["rag-documents"], queryFn: listDocuments });

  const [file, setFile] = useState<File | null>(null);
  // Remount key for the file input: after a successful upload the browser
  // input must be cleared so selecting the same file again fires onChange.
  const [fileInputKey, setFileInputKey] = useState(0);
  const [chunker, setChunker] = useState<string | null>(null);
  const [embedder, setEmbedder] = useState<string | null>(null);
  const [chunkSize, setChunkSize] = useState("");
  const [chunkOverlap, setChunkOverlap] = useState("");
  const [preview, setPreview] = useState<UploadResponse | null>(null);
  const [pendingDelete, setPendingDelete] = useState<DocumentRow | null>(null);

  // Fall back to the server's defaults until the user overrides a stage, so
  // the form is usable before the catalog query resolves.
  const effectiveChunker = chunker ?? catalog.data?.defaults.chunker ?? "";
  const effectiveEmbedder = embedder ?? catalog.data?.defaults.embedder ?? "";

  // Whole numbers only. A fractional value would otherwise be silently
  // dropped (falling back to the server default) or rejected as a 422 whose
  // message does not point at the field.
  const chunkSizeValue = parseWholeNumber(chunkSize);
  const chunkOverlapValue = parseWholeNumber(chunkOverlap);
  const chunkSizeInvalid =
    chunkSize.trim() !== "" && (chunkSizeValue === undefined || chunkSizeValue < 1);
  const chunkOverlapInvalid = chunkOverlap.trim() !== "" && chunkOverlapValue === undefined;
  const overlapNotSmaller =
    chunkSizeValue !== undefined &&
    chunkOverlapValue !== undefined &&
    chunkOverlapValue >= chunkSizeValue;
  const sizesInvalid = chunkSizeInvalid || chunkOverlapInvalid || overlapNotSmaller;

  const invalidateDocuments = () =>
    void queryClient.invalidateQueries({ queryKey: ["rag-documents"] });
  // The stage catalog carries the corpus embedder list, which changes when a
  // document is indexed or deleted. Refetch it after either mutation so the
  // chat page's query-embedder choices stay truthful.
  const invalidateCatalog = () =>
    void queryClient.invalidateQueries({ queryKey: ["rag-stages"] });

  const upload = useMutation({
    mutationFn: () => {
      if (!file) throw new Error(t("rag.documents.fileRequired"));
      if (sizesInvalid) throw new Error(t("rag.documents.invalidInteger", { min: 1 }));
      return uploadDocument({
        file,
        chunker: effectiveChunker || undefined,
        embedder: effectiveEmbedder || undefined,
        chunkSize: chunkSizeValue,
        chunkOverlap: chunkOverlapValue,
      });
    },
    onSuccess: (data) => {
      setPreview(data);
      setFile(null);
      setFileInputKey((key) => key + 1);
      toast.success(t("rag.documents.uploadedToast", { count: data.chunk_count }));
    },
    onError: (error) => toast.error(apiErrorMessage(error)),
    // A rejected re-upload can still create a `failed` row server-side, so
    // the list must refetch on failure too.
    onSettled: () => {
      invalidateDocuments();
      invalidateCatalog();
    },
  });

  const index = useMutation({
    mutationFn: ({ documentId, targetEmbedder }: { documentId: string; targetEmbedder?: string }) =>
      indexDocument(documentId, { embedder: targetEmbedder }),
    onSuccess: (data) => {
      setPreview((current) => {
        if (!current || current.document_id !== data.document_id) return current;
        return {
          ...current,
          status: data.status,
          dim: data.dim,
          embedder: data.embedder,
          chunk_count: data.chunk_count,
        };
      });
      toast.success(t("rag.documents.indexedToast", { count: data.chunk_count }));
    },
    onError: (error) => toast.error(apiErrorMessage(error)),
    // Failures matter as much as successes: the server marks the document
    // `failed` or leaves an existing version untouched, and the row must
    // reflect whichever happened.
    onSettled: () => {
      invalidateDocuments();
      invalidateCatalog();
    },
  });

  const remove = useMutation({
    mutationFn: (documentId: string) => deleteDocument(documentId),
    onSuccess: (data) => {
      setPreview((current) =>
        current && current.document_id === data.document_id ? null : current,
      );
      toast.success(t("rag.documents.deletedToast"));
    },
    onError: (error) => toast.error(apiErrorMessage(error)),
    onSettled: () => {
      setPendingDelete(null);
      invalidateDocuments();
      invalidateCatalog();
    },
  });

  const rows: DocumentRow[] = documents.data?.items ?? [];
  // Once indexed, the preview stays indexable only while the user is asking
  // for a different embedder; that is a deliberate re-embed, not a no-op.
  const previewEmbedderChanged =
    preview !== null && effectiveEmbedder !== "" && effectiveEmbedder !== preview.embedder;

  return (
    <div className="space-y-6">
      <section className="space-y-2">
        <h1 className="text-2xl font-semibold tracking-tight">{t("rag.documents.title")}</h1>
        <p className="text-muted-foreground max-w-2xl">{t("rag.documents.description")}</p>
      </section>

      {canWrite ? (
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
                key={fileInputKey}
                id="rag-file"
                type="file"
                onChange={(event) => setFile(event.target.files?.[0] ?? null)}
                disabled={upload.isPending}
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
                    step={1}
                    value={chunkSize}
                    onChange={(event) => setChunkSize(event.target.value)}
                    placeholder={t("rag.documents.chunkSizePlaceholder")}
                  />
                  {chunkSizeInvalid ? (
                    <p className="text-destructive text-xs">
                      {t("rag.documents.invalidInteger", { min: 1 })}
                    </p>
                  ) : (
                    <p className="text-muted-foreground text-xs">
                      {t("rag.documents.chunkSizeHint")}
                    </p>
                  )}
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="rag-chunk-overlap">
                    {t("rag.documents.chunkOverlapLabel")}
                  </Label>
                  <Input
                    id="rag-chunk-overlap"
                    type="number"
                    min={0}
                    step={1}
                    value={chunkOverlap}
                    onChange={(event) => setChunkOverlap(event.target.value)}
                    placeholder={t("rag.documents.chunkOverlapPlaceholder")}
                  />
                  {chunkOverlapInvalid ? (
                    <p className="text-destructive text-xs">
                      {t("rag.documents.invalidInteger", { min: 0 })}
                    </p>
                  ) : overlapNotSmaller ? (
                    <p className="text-destructive text-xs">
                      {t("rag.documents.overlapTooLarge")}
                    </p>
                  ) : (
                    <p className="text-muted-foreground text-xs">
                      {t("rag.documents.chunkOverlapHint")}
                    </p>
                  )}
                </div>
              </div>
            </details>

            <Button
              onClick={() => upload.mutate()}
              disabled={!file || upload.isPending || sizesInvalid}
              className="w-full md:w-auto"
            >
              {upload.isPending ? t("rag.documents.previewing") : t("rag.documents.preview")}
            </Button>
          </CardContent>
        </Card>
      ) : (
        <p className="text-muted-foreground text-sm">{t("rag.documents.readOnly")}</p>
      )}

      {canWrite && preview ? (
        <Card>
          <CardHeader>
            <CardTitle className="flex flex-wrap items-center gap-2">
              {t("rag.documents.previewTitle")}
              <DocumentStatusBadge status={preview.status} />
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
                onClick={() =>
                  index.mutate({
                    documentId: preview.document_id,
                    // Send the selector's current value: the user is allowed
                    // to change the embedder after seeing the chunks, and
                    // omitting it would leave the upload-time choice in force.
                    targetEmbedder: effectiveEmbedder || undefined,
                  })
                }
                disabled={
                  index.isPending || (preview.status === "indexed" && !previewEmbedderChanged)
                }
              >
                {index.isPending ? t("rag.documents.indexing") : t("rag.documents.index")}
              </Button>
              <span className="text-muted-foreground text-xs">
                {preview.status === "indexed"
                  ? previewEmbedderChanged
                    ? t("rag.documents.reindexHint")
                    : t("rag.documents.alreadyIndexed")
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
          ) : documents.isLoading ? (
            <p className="text-muted-foreground text-sm">{t("rag.documents.loading")}</p>
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
                  {canWrite ? (
                    <TableHead className="text-right">{t("rag.common.actions")}</TableHead>
                  ) : null}
                </TableRow>
              </TableHeader>
              <TableBody>
                {rows.map((row) => (
                  <TableRow key={row.id}>
                    <TableCell>
                      <div className="font-medium">{row.title}</div>
                      {row.failure_reason ? (
                        <DocumentFailureReason reason={row.failure_reason} />
                      ) : null}
                    </TableCell>
                    <TableCell>
                      <DocumentStatusBadge status={row.status} />
                    </TableCell>
                    <TableCell className="font-mono text-xs">{row.chunker_id}</TableCell>
                    <TableCell className="font-mono text-xs">
                      {row.embedder_id} · {row.dim}d
                    </TableCell>
                    <TableCell className="text-right">{row.chunk_count}</TableCell>
                    <TableCell className="text-muted-foreground text-xs">
                      {formatDocumentTimestamp(row.updated_at, i18n.language)}
                    </TableCell>
                    {canWrite ? (
                      <TableCell className="text-right">
                        <div className="flex justify-end gap-2">
                          {row.status === "pending" ? (
                            <Button
                              size="sm"
                              variant="outline"
                              onClick={() => index.mutate({ documentId: row.id })}
                              disabled={index.isPending}
                            >
                              {t("rag.documents.indexRow")}
                            </Button>
                          ) : null}
                          <Button
                            size="sm"
                            variant="ghost"
                            aria-label={t("rag.documents.delete")}
                            onClick={() => setPendingDelete(row)}
                            disabled={remove.isPending}
                          >
                            <Trash2Icon className="size-4" />
                          </Button>
                        </div>
                      </TableCell>
                    ) : null}
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      <ConfirmDialog
        open={pendingDelete !== null}
        onOpenChange={(open) => {
          if (!open) setPendingDelete(null);
        }}
        title={t("rag.documents.deleteConfirmTitle")}
        description={t("rag.documents.deleteConfirmDescription", {
          title: pendingDelete?.title ?? "",
        })}
        confirmLabel={t("rag.documents.delete")}
        pending={remove.isPending}
        onConfirm={() => {
          if (pendingDelete) remove.mutate(pendingDelete.id);
        }}
      />
    </div>
  );
}
