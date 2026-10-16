import { useTranslation } from "react-i18next";

import { Badge } from "@/components/ui/badge";

/**
 * The caller's self-declared agent identity, as recorded in audit rows.
 *
 * `unknown` is rendered as an outline chip rather than a filled one: it is
 * the server's normalisation for "no header / not on the whitelist", i.e.
 * the one value that carries no information, and it should not look like a
 * recognised agent. The id (a per-installation string) stays monospaced.
 */
export function AgentBadge({ type, id }: { type?: string; id?: string }) {
  const { t } = useTranslation();
  const label = type || t("mcp.common.unknownAgent");
  const recognised = Boolean(type) && type !== "unknown";

  return (
    <span className="inline-flex max-w-full items-center gap-1.5">
      <Badge variant={recognised ? "secondary" : "outline"} className="shrink-0">
        {label}
      </Badge>
      {id ? (
        <span className="text-muted-foreground truncate font-mono text-xs" title={id}>
          {id}
        </span>
      ) : null}
    </span>
  );
}
