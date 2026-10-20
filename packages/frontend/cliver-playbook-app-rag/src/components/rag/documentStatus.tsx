import { useTranslation } from "react-i18next";

import { Badge } from "cliver-playbook-app-basic/components/ui/badge.tsx";

/**
 * Document lifecycle presentation shared by the knowledge-base pages.
 *
 * Status is a server-owned string, not a closed enum: the UI maps the three
 * known values to a badge variant and a message key, and falls back to the
 * raw value so a state added on the server still renders (rather than
 * disappearing) before the frontend catches up.
 *
 * Timestamps are formatted with the active i18n language rather than the
 * browser's default locale: the application can be switched to a language
 * that differs from the OS setting, and dates should follow the UI.
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

/** Server failure codes get localized text; an unrecognized code still
 * renders verbatim so a new server reason is visible before the UI maps it. */
const FAILURE_LABEL: Record<string, string> = {
  empty_after_parse: "rag.documents.failure.emptyAfterParse",
  chunking_failed: "rag.documents.failure.chunkingFailed",
  embedding_failed: "rag.documents.failure.embeddingFailed",
  unknown_embedder: "rag.documents.failure.unknownEmbedder",
  no_chunks: "rag.documents.failure.noChunks",
};

export function DocumentStatusBadge({ status }: { status: string }) {
  const { t } = useTranslation();
  const label = STATUS_LABEL[status] ? t(STATUS_LABEL[status]) : status;
  return <Badge variant={STATUS_VARIANT[status] ?? "outline"}>{label}</Badge>;
}

export function DocumentFailureReason({ reason }: { reason: string }) {
  const { t } = useTranslation();
  return (
    <div className="text-destructive text-xs">
      {FAILURE_LABEL[reason] ? t(FAILURE_LABEL[reason]) : reason}
    </div>
  );
}

export function formatDocumentTimestamp(value: string | null, locale: string): string {
  if (!value) return "—";
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString(locale);
}
