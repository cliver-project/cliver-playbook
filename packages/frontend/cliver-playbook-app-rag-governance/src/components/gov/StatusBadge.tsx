import { useTranslation } from "react-i18next";

import { Badge } from "cliver-playbook-app-basic/components/ui/badge.tsx";

/**
 * One badge for every governance state machine.
 *
 * The server owns the enums; this maps each value to a look and a
 * translation key under `gov.status.*`. Unknown values still render (the
 * demo must survive a server a release ahead of the UI) with the raw value.
 */
const TONE_BY_STATUS: Record<string, "default" | "secondary" | "destructive" | "outline"> = {
  // project
  draft: "secondary",
  baseline_eval: "default",
  active: "default",
  paused: "outline",
  archived: "outline",
  // batch
  queued: "secondary",
  running: "secondary",
  staged: "default",
  review_pending: "default",
  approved: "default",
  published: "default",
  rejected: "destructive",
  failed: "destructive",
  // golden set
  candidate: "secondary",
  confirmed: "default",
  // rule set
  proposed: "secondary",
  // archived above
  // eval run
  passed: "default",
};

export function StatusBadge({ status }: { status: string }) {
  const { t } = useTranslation();
  const key = `gov.status.${status}`;
  const label = t(key) === key ? status : t(key);
  return <Badge variant={TONE_BY_STATUS[status] ?? "outline"}>{label}</Badge>;
}
