import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";

import { listMcpCalls, type McpCallRow } from "cliver-playbook-app-mcp/api/mcp.ts";
import { AgentBadge } from "cliver-playbook-app-mcp/components/mcp/AgentBadge.tsx";
import { Badge } from "cliver-playbook-app-basic/components/ui/badge.tsx";
import { Button } from "cliver-playbook-app-basic/components/ui/button.tsx";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "cliver-playbook-app-basic/components/ui/card.tsx";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "cliver-playbook-app-basic/components/ui/table.tsx";

/**
 * Who calls this server's tools — the operator's view of the MCP boundary.
 *
 * Data comes from `/api/v1/mcp/calls` (gated on `mcp:agents:read`), which
 * returns tool calls AND gate rejections: a rejected agent is exactly the
 * event an operator must not have to dig for. Rows carry the self-declared
 * agent identity (`agent_type` / `agent_id` headers or env vars, already
 * normalised against the whitelist server-side) next to the authenticated
 * user, which is the pairing the whole audit design exists for: "which
 * machine, on whose behalf".
 *
 * The per-agent summary is computed from the newest WINDOW rows rather
 * than aggregated in SQL — bounded, honest and enough for an admin glance;
 * a dedicated aggregate endpoint is a deliberate non-goal until someone
 * needs decade-scale history.
 */

const WINDOW = 200;

interface AgentSummary {
  type: string;
  calls: number;
  failures: number;
  lastSeen: string;
}

function summarise(rows: McpCallRow[]): AgentSummary[] {
  const byType = new Map<string, AgentSummary>();
  for (const row of rows) {
    const type = row.detail.agent_type || "unknown";
    const entry = byType.get(type) ?? { type, calls: 0, failures: 0, lastSeen: row.created_at };
    entry.calls += 1;
    if (!row.ok) entry.failures += 1;
    // Rows arrive newest-first, but compare anyway — the summary must not
    // depend on the server's ordering.
    if (row.created_at > entry.lastSeen) entry.lastSeen = row.created_at;
    byType.set(type, entry);
  }
  return [...byType.values()].sort(
    (a, b) => b.calls - a.calls || a.type.localeCompare(b.type),
  );
}

export default function MCPAgentsPage() {
  const { t } = useTranslation();

  const calls = useQuery({
    queryKey: ["mcp-calls", { limit: WINDOW }],
    queryFn: () => listMcpCalls(WINDOW),
  });

  // Stable reference for the summary: `?? []` alone would mint a new
  // array every render and re-run the aggregation on each one.
  const rows = useMemo(() => calls.data?.items ?? [], [calls.data]);
  const agents = useMemo(() => summarise(rows), [rows]);

  return (
    <div className="space-y-6">
      <section className="space-y-2">
        <h1 className="text-2xl font-semibold tracking-tight">{t("mcp.agents.title")}</h1>
        <p className="text-muted-foreground max-w-2xl">{t("mcp.agents.description")}</p>
      </section>

      <Card>
        <CardHeader>
          <CardTitle>{t("mcp.agents.summaryTitle")}</CardTitle>
          <CardDescription>
            {t("mcp.agents.summaryDescription", { count: rows.length })}
          </CardDescription>
        </CardHeader>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>{t("mcp.agents.agent")}</TableHead>
                <TableHead>{t("mcp.agents.calls")}</TableHead>
                <TableHead>{t("mcp.agents.failures")}</TableHead>
                <TableHead>{t("mcp.agents.lastSeen")}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {agents.length > 0 ? (
                agents.map((agent) => (
                  <TableRow key={agent.type}>
                    <TableCell>
                      <AgentBadge type={agent.type} />
                    </TableCell>
                    <TableCell className="text-sm">{agent.calls}</TableCell>
                    <TableCell className="text-sm">
                      {agent.failures > 0 ? (
                        <Badge variant="destructive">{agent.failures}</Badge>
                      ) : (
                        <span className="text-muted-foreground">0</span>
                      )}
                    </TableCell>
                    <TableCell className="text-muted-foreground text-xs">
                      {new Date(agent.lastSeen).toLocaleString()}
                    </TableCell>
                  </TableRow>
                ))
              ) : (
                <TableRow>
                  <TableCell colSpan={4} className="text-muted-foreground">
                    {calls.isLoading ? t("common.loading") : t("mcp.agents.empty")}
                  </TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="flex-row items-center justify-between gap-4">
          <div className="space-y-1">
            <CardTitle>{t("mcp.agents.recentTitle")}</CardTitle>
            <CardDescription>
              {t("mcp.agents.total", { shown: rows.length, total: calls.data?.total ?? 0 })}
            </CardDescription>
          </div>
          <Button
            variant="outline"
            size="sm"
            disabled={calls.isFetching}
            onClick={() => void calls.refetch()}
          >
            {t("mcp.agents.refresh")}
          </Button>
        </CardHeader>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>{t("mcp.agents.when")}</TableHead>
                <TableHead>{t("mcp.agents.agent")}</TableHead>
                <TableHead>{t("mcp.agents.user")}</TableHead>
                <TableHead>{t("mcp.agents.tool")}</TableHead>
                <TableHead>{t("mcp.agents.outcome")}</TableHead>
                <TableHead>{t("mcp.agents.duration")}</TableHead>
                <TableHead>{t("mcp.agents.args")}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.length > 0 ? (
                rows.map((row) => (
                  <TableRow key={row.id}>
                    <TableCell className="text-muted-foreground whitespace-nowrap text-xs">
                      {new Date(row.created_at).toLocaleString()}
                    </TableCell>
                    <TableCell>
                      <AgentBadge type={row.detail.agent_type} id={row.detail.agent_id} />
                    </TableCell>
                    <TableCell className="text-sm">
                      {row.username || t("mcp.agents.anonymous")}
                    </TableCell>
                    <TableCell className="font-mono text-xs">{row.target}</TableCell>
                    <TableCell>
                      {row.ok ? (
                        <Badge variant="secondary">{t("mcp.agents.ok")}</Badge>
                      ) : (
                        <Badge variant="destructive" className="max-w-48 truncate" title={row.error}>
                          {row.error || t("mcp.agents.failed")}
                        </Badge>
                      )}
                    </TableCell>
                    <TableCell className="text-muted-foreground text-xs">
                      {row.detail.duration_ms ? `${row.detail.duration_ms} ms` : "—"}
                    </TableCell>
                    <TableCell className="text-muted-foreground max-w-56 truncate font-mono text-xs">
                      {row.detail.args && Object.keys(row.detail.args).length > 0
                        ? JSON.stringify(row.detail.args)
                        : "—"}
                    </TableCell>
                  </TableRow>
                ))
              ) : (
                <TableRow>
                  <TableCell colSpan={7} className="text-muted-foreground">
                    {calls.isLoading ? t("common.loading") : t("mcp.agents.empty")}
                  </TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
        </CardContent>
      </Card>
    </div>
  );
}
