import { CopyIcon } from "lucide-react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";

import { Button } from "cliver-playbook-app-basic/components/ui/button.tsx";

/**
 * Copy-to-clipboard button for the values an operator has to move into
 * another program verbatim (the MCP endpoint URL, the CLI snippet) — a
 * hand-selected URL is a misconfiguration waiting to happen.
 *
 * Uses the async clipboard API; on non-secure contexts (plain-HTTP LAN
 * deployments, where the API is unavailable) the failure is surfaced as a
 * toast instead of a silent no-op, and the value stays visible for manual
 * selection.
 */
export function CopyButton({ value, label }: { value: string; label?: string }) {
  const { t } = useTranslation();

  async function handleCopy() {
    try {
      await navigator.clipboard.writeText(value);
      toast.success(t("mcp.common.copied"));
    } catch {
      toast.error(t("mcp.common.copyFailed"));
    }
  }

  return (
    <Button type="button" variant="outline" size="sm" onClick={() => void handleCopy()}>
      <CopyIcon className="size-3.5" />
      {label ?? t("mcp.common.copy")}
    </Button>
  );
}
