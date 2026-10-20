import { useTranslation } from "react-i18next";

import type { PreviewChunk } from "cliver-playbook-app-rag/api/rag.ts";

/**
 * What the chosen chunker produced, rendered before the user commits to an
 * embedder.
 *
 * This is the point of the two-phase ingestion flow: chunk boundaries and
 * token counts are cheap to inspect, embedding is not. The preview is capped
 * by the server; when it was truncated the footer says so rather than
 * implying the document has only these chunks.
 */
export function ChunkPreview({
  chunks,
  truncated,
}: {
  chunks: PreviewChunk[];
  truncated: boolean;
}) {
  const { t } = useTranslation();

  if (chunks.length === 0) {
    return <p className="text-muted-foreground text-sm">{t("rag.documents.previewEmpty")}</p>;
  }

  return (
    <div className="space-y-2">
      <div className="max-h-80 space-y-2 overflow-y-auto pr-1">
        {chunks.map((chunk) => (
          <div key={chunk.chunk_id_prefix} className="rounded-md border p-3">
            <div className="text-muted-foreground mb-1 flex flex-wrap items-center gap-3 text-xs">
              <span>
                {t("rag.documents.chunkOrdinal", { ordinal: chunk.ordinal })}
              </span>
              <span>
                {t("rag.documents.chunkTokens", { count: chunk.token_count })}
              </span>
              <code className="font-mono">{chunk.chunk_id_prefix}</code>
            </div>
            <p className="text-sm whitespace-pre-wrap">{chunk.text}</p>
          </div>
        ))}
      </div>
      {truncated ? (
        <p className="text-muted-foreground text-xs">{t("rag.documents.previewTruncated")}</p>
      ) : null}
    </div>
  );
}
