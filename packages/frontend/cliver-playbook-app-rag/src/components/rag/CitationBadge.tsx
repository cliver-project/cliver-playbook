import type { Citation } from "cliver-playbook-app-rag/api/rag.ts";
import { Badge } from "cliver-playbook-app-basic/components/ui/badge.tsx";

/**
 * A compact pointer from an answer to the chunk that supports it.
 *
 * The badge carries the chunk's ordinal and a short id prefix — enough to find
 * the chunk in the document view — while the full preview text stays in the
 * hover title so a dense answer does not become a wall of duplicated context.
 */
export function CitationBadge({ citation }: { citation: Citation }) {
  return (
    <Badge variant="secondary" title={citation.text_preview} className="font-mono">
      #{citation.ordinal} · {citation.chunk_id.slice(0, 8)}
    </Badge>
  );
}
