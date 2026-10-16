import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";

import { apiErrorMessage } from "@/api/client";
import {
  callMcpTool,
  fetchMcpInfo,
  listMcpCalls,
  listMcpTools,
  mcpEndpointUrl,
  type McpToolResult,
} from "@/api/mcp";
import { useAuth } from "@/components/auth/AuthContext";
import { AgentBadge } from "@/components/mcp/AgentBadge";
import { CopyButton } from "@/components/mcp/CopyButton";
import { AlertCircleIcon } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Textarea } from "@/components/ui/textarea";

/**
 * MCP playground: exercise this server's tools over the real wire protocol.
 *
 * The page is a genuine MCP client, not a shortcut into the tool functions —
 * it POSTs JSON-RPC to the endpoint an external agent would use, with the
 * signed-in user's own session token as the bearer. That makes it the
 * fastest way to answer "does my auth setup work, and what does an agent
 * actually see": the response panel shows the exact text blocks a model
 * would read, permission denials included (a denial is a successful
 * JSON-RPC exchange reporting a failed tool call, which is why it renders
 * as a result, not as a page error).
 *
 * Every call lands in the audit trail under agent type `web-playground`;
 * the recent-calls strip below (display-gated on `mcp:agents:read`, which
 * the server enforces independently) closes that loop.
 */

/** Parse the arguments textarea into a JSON object, with actionable errors. */
function parseArgs(raw: string, t: (key: string) => string): Record<string, unknown> {
  if (!raw.trim()) return {};
  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    throw new Error(t("mcp.playground.argsInvalid"));
  }
  if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) {
    throw new Error(t("mcp.playground.argsObjectRequired"));
  }
  return parsed as Record<string, unknown>;
}

const RECENT_LIMIT = 8;

export default function MCPPlaygroundPage() {
  const { t } = useTranslation();
  const { hasPerm } = useAuth();
  const queryClient = useQueryClient();

  const info = useQuery({ queryKey: ["mcp-info"], queryFn: fetchMcpInfo });
  const mountPath = info.data?.mount_path ?? "/mcp";
  const endpoint = mcpEndpointUrl(mountPath);

  // Wait for /mcp/info before listing: the mount path is a setting, and a
  // guessed path would produce a confusing 404 wall instead of the tools.
  const tools = useQuery({
    queryKey: ["mcp-tools", mountPath],
    queryFn: () => listMcpTools(mountPath),
    enabled: info.isSuccess,
    retry: false,
  });

  const [toolName, setToolName] = useState("");
  const [argsText, setArgsText] = useState("");
  const [result, setResult] = useState<McpToolResult | null>(null);

  const selectedTool = tools.data?.find((tool) => tool.name === toolName);

  const call = useMutation({
    mutationFn: () => callMcpTool(mountPath, toolName, parseArgs(argsText, t)),
    onSuccess: (data) => {
      setResult(data);
      // The call just wrote an audit row — show it in the strip below
      // without making the operator hit refresh.
      void queryClient.invalidateQueries({ queryKey: ["mcp-calls"] });
    },
    onError: (error) => toast.error(error instanceof Error ? error.message : String(error)),
  });

  const recent = useQuery({
    queryKey: ["mcp-calls", { limit: RECENT_LIMIT }],
    queryFn: () => listMcpCalls(RECENT_LIMIT),
    enabled: hasPerm("mcp:agents:read"),
  });

  return (
    <div className="space-y-6">
      <section className="space-y-2">
        <h1 className="text-2xl font-semibold tracking-tight">{t("mcp.playground.title")}</h1>
        <p className="text-muted-foreground max-w-2xl">{t("mcp.playground.description")}</p>
      </section>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            {t("mcp.playground.endpointTitle")}
            {info.data ? (
              <Badge variant={info.data.auth_enabled ? "secondary" : "destructive"}>
                {info.data.auth_enabled ? t("mcp.playground.authOn") : t("mcp.playground.authOff")}
              </Badge>
            ) : null}
          </CardTitle>
          <CardDescription>{t("mcp.playground.endpointDescription")}</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {info.isError ? (
            <p className="text-destructive flex items-center gap-2 text-sm">
              <AlertCircleIcon className="size-4" />
              {apiErrorMessage(info.error)}
            </p>
          ) : (
            <>
              <div className="flex items-center gap-2">
                <code className="bg-muted min-w-0 flex-1 truncate rounded-md px-2 py-1.5 font-mono text-xs">
                  {endpoint}
                </code>
                <CopyButton value={endpoint} />
              </div>

              {info.data?.auth_enabled === false ? (
                <p className="border-destructive/50 text-destructive rounded-md border px-3 py-2 text-sm">
                  {t("mcp.playground.authOffWarning")}
                </p>
              ) : (
                <p className="text-muted-foreground text-sm">{t("mcp.playground.authOnNote")}</p>
              )}

              <div className="space-y-1.5">
                <Label>{t("mcp.playground.cliHint")}</Label>
                <div className="flex items-center gap-2">
                  <code className="bg-muted min-w-0 flex-1 truncate rounded-md px-2 py-1.5 font-mono text-xs">
                    claude mcp add --transport http {info.data?.server_name ?? "mcp"} {endpoint}
                  </code>
                  <CopyButton
                    value={`claude mcp add --transport http ${info.data?.server_name ?? "mcp"} ${endpoint}`}
                  />
                </div>
                <p className="text-muted-foreground text-xs">{t("mcp.playground.headersHint")}</p>
              </div>
            </>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>{t("mcp.playground.toolsTitle")}</CardTitle>
          <CardDescription>{t("mcp.playground.toolsDescription")}</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {tools.isError ? (
            <p className="text-destructive flex items-center gap-2 text-sm">
              <AlertCircleIcon className="size-4" />
              {t("mcp.playground.toolsFailed")} ({apiErrorMessage(tools.error)})
            </p>
          ) : null}

          <div className="grid gap-6 md:grid-cols-2">
            <div className="space-y-3">
              <div className="space-y-1.5">
                <Label>{t("mcp.playground.toolLabel")}</Label>
                <Select
                  value={toolName}
                  onValueChange={(value) => {
                    setToolName(value);
                    setResult(null);
                  }}
                >
                  <SelectTrigger className="w-full">
                    <SelectValue placeholder={t("mcp.playground.selectTool")} />
                  </SelectTrigger>
                  <SelectContent>
                    {(tools.data ?? []).map((tool) => (
                      <SelectItem key={tool.name} value={tool.name}>
                        {tool.name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>

              <div className="space-y-1.5">
                <Label htmlFor="mcp-args">{t("mcp.playground.argsLabel")}</Label>
                <Textarea
                  id="mcp-args"
                  value={argsText}
                  onChange={(event) => setArgsText(event.target.value)}
                  placeholder='{"message": "hello"}'
                  rows={5}
                  spellCheck={false}
                  className="font-mono text-xs"
                />
              </div>

              <Button
                disabled={!toolName || call.isPending}
                onClick={() => call.mutate()}
                className="w-full md:w-auto"
              >
                {call.isPending ? t("mcp.playground.calling") : t("mcp.playground.call")}
              </Button>
            </div>

            <div className="space-y-3">
              {selectedTool ? (
                <div className="space-y-1.5">
                  <p className="text-muted-foreground text-xs whitespace-pre-wrap">
                    {selectedTool.description}
                  </p>
                  {selectedTool.inputSchema ? (
                    <details>
                      <summary className="text-muted-foreground cursor-pointer text-xs">
                        {t("mcp.playground.inputSchema")}
                      </summary>
                      <pre className="bg-muted mt-1 overflow-x-auto rounded-md p-2 text-xs">
                        {JSON.stringify(selectedTool.inputSchema, null, 2)}
                      </pre>
                    </details>
                  ) : null}
                </div>
              ) : null}

              {result ? (
                <div className="space-y-2 rounded-md border p-3">
                  <div className="flex items-center gap-2">
                    <Badge variant={result.isError ? "destructive" : "secondary"}>
                      {result.isError ? t("mcp.playground.toolError") : t("mcp.playground.toolOk")}
                    </Badge>
                    <span className="text-muted-foreground text-xs">
                      {t("mcp.playground.duration", { ms: result.durationMs })}
                    </span>
                  </div>
                  <pre className="overflow-x-auto text-xs whitespace-pre-wrap">
                    {result.text || "—"}
                  </pre>
                  {result.structured !== undefined ? (
                    <details>
                      <summary className="text-muted-foreground cursor-pointer text-xs">
                        {t("mcp.playground.structured")}
                      </summary>
                      <pre className="bg-muted mt-1 overflow-x-auto rounded-md p-2 text-xs">
                        {JSON.stringify(result.structured, null, 2)}
                      </pre>
                    </details>
                  ) : null}
                </div>
              ) : (
                <p className="text-muted-foreground text-sm">{t("mcp.playground.resultEmpty")}</p>
              )}
            </div>
          </div>
        </CardContent>
      </Card>

      {hasPerm("mcp:agents:read") ? (
        <Card>
          <CardHeader className="flex-row items-center justify-between gap-4">
            <div className="space-y-1">
              <CardTitle>{t("mcp.playground.recentTitle")}</CardTitle>
              <CardDescription>{t("mcp.playground.recentDescription")}</CardDescription>
            </div>
            <Button asChild variant="outline" size="sm">
              <Link to="/mcp/agents">{t("mcp.playground.fullAudit")}</Link>
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
                </TableRow>
              </TableHeader>
              <TableBody>
                {recent.data && recent.data.items.length > 0 ? (
                  recent.data.items.map((row) => (
                    <TableRow key={row.id}>
                      <TableCell className="text-muted-foreground whitespace-nowrap text-xs">
                        {new Date(row.created_at).toLocaleTimeString()}
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
                          <Badge variant="destructive" title={row.error}>
                            {row.error || t("mcp.agents.failed")}
                          </Badge>
                        )}
                      </TableCell>
                    </TableRow>
                  ))
                ) : (
                  <TableRow>
                    <TableCell colSpan={5} className="text-muted-foreground">
                      {t("mcp.playground.recentEmpty")}
                    </TableCell>
                  </TableRow>
                )}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      ) : null}
    </div>
  );
}
