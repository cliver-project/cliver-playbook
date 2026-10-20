import axios from "axios";

import { api } from "cliver-playbook-app-basic/api/client.ts";
import type { AuditLogRow } from "cliver-playbook-app-user/api/auth.ts";
import { getStoredToken } from "cliver-playbook-app-user/auth/session.ts";

/**
 * MCP-domain API calls (the mcp package).
 *
 * Two very different call paths share this module:
 *
 * - `/api/v1/mcp/*` — ordinary Web API through the shared axios instance
 *   (base URL, bearer injection, 401 redirect all apply).
 * - The MCP endpoint itself — raw JSON-RPC over POST, deliberately bypassing
 *   the shared instance: it lives outside /api/v1, requires the spec-mandated
 *   Accept header (the server answers 406 without it), answers with SSE
 *   (`text/event-stream`) when the client accepts it, and speaks JSON-RPC
 *   errors rather than FastAPI's shape — so the shared error helpers would
 *   misread it.
 *
 * The playground in the Web UI is itself a client of this module, which is
 * the point: the browser exercises the exact wire protocol an external agent
 * (Claude Code, WorkBuddy, a script) will use, with the signed-in user's own
 * session token as the bearer.
 */

// ---------------------------------------------------------------------------
// Discovery
// ---------------------------------------------------------------------------

export interface McpInfo {
  server_name: string;
  mount_path: string;
  auth_enabled: boolean;
}

export async function fetchMcpInfo(): Promise<McpInfo> {
  const { data } = await api.get<McpInfo>("/mcp/info");
  return data;
}

/** Public URL of the MCP endpoint. Same-origin by default (the Vite dev
 * proxy forwards /mcp to the backend); VITE_API_BASE_URL points it at a
 * split deployment the same way it points the API client. */
export function mcpEndpointUrl(mountPath: string): string {
  const base = import.meta.env.VITE_API_BASE_URL ?? "";
  return base ? `${base}${mountPath}` : `${window.location.origin}${mountPath}`;
}

// ---------------------------------------------------------------------------
// JSON-RPC transport
// ---------------------------------------------------------------------------

/** Agent type this page declares on the wire; whitelisted in
 * settings.mcp.agent_type_whitelist so audit rows attribute the Web UI's
 * own console distinctly from an unidentified client. */
const PLAYGROUND_AGENT_TYPE = "web-playground";

/** One request must not hang the page: the SDK answers a request-bearing
 * POST with a single SSE frame and closes the stream, so anything slower
 * than this is a broken deployment, not a slow tool. */
const RPC_TIMEOUT_MS = 30_000;

let rpcCounter = 0;

interface JsonRpcEnvelope {
  jsonrpc: string;
  id: number | null;
  result?: unknown;
  error?: { code: number; message: string };
}

/** Decode the JSON-RPC envelope from either response flavour.
 *
 * The SDK's streamable-http server replies `text/event-stream` whenever
 * the client accepts it (and this client must, per spec). Each `data:`
 * line is one complete JSON-RPC frame; a request-bearing POST yields
 * exactly one, but taking the last parseable frame keeps the parser
 * correct if a future server prepends notifications. */
function parseEnvelope(raw: string, contentType: string): JsonRpcEnvelope {
  if (contentType.includes("text/event-stream")) {
    let envelope: JsonRpcEnvelope | null = null;
    for (const line of raw.split(/\r?\n/)) {
      if (!line.startsWith("data:")) continue;
      const payload = line.slice(5).trim();
      if (!payload) continue;
      try {
        envelope = JSON.parse(payload) as JsonRpcEnvelope;
      } catch {
        // A frame this client cannot read is not its answer; keep scanning.
      }
    }
    if (envelope === null) {
      throw new Error(`Could not parse the SSE response: ${raw.slice(0, 200)}`);
    }
    return envelope;
  }
  return JSON.parse(raw) as JsonRpcEnvelope;
}

/** Turn a transport failure into something a human can act on.
 * The MCP gate answers 401/403 with `{error, error_description}` (RFC 9728
 * flavour), NOT FastAPI's `{detail}` — and an intermediate proxy may answer
 * HTML, so every fallback ends at the status line. */
function transportErrorMessage(error: unknown): string {
  if (axios.isAxiosError(error)) {
    const response = error.response;
    if (response) {
      try {
        const body = JSON.parse(String(response.data)) as {
          error?: string;
          error_description?: string;
        };
        if (body.error) {
          return `HTTP ${response.status} ${body.error}${body.error_description ? `: ${body.error_description}` : ""}`;
        }
      } catch {
        // Not JSON (proxy error page etc.) — fall through to the status line.
      }
      return `HTTP ${response.status} ${response.statusText}`;
    }
    return error.message;
  }
  return String(error);
}

async function rpc<T>(
  mountPath: string,
  method: string,
  params: Record<string, unknown>,
): Promise<{ result: T; durationMs: number }> {
  const id = ++rpcCounter;
  const started = performance.now();
  const token = getStoredToken();

  let response;
  try {
    response = await axios.post(
      mcpEndpointUrl(mountPath),
      { jsonrpc: "2.0", id, method, params },
      {
        // Manual decoding: axios would auto-parse only application/json and
        // leave the SSE body as an unread string — one parser for both.
        responseType: "text",
        timeout: RPC_TIMEOUT_MS,
        headers: {
          "Content-Type": "application/json",
          // The spec (and this server, observed) requires the client to
          // accept BOTH content types — a missing text/event-stream is a 406.
          Accept: "application/json, text/event-stream",
          "X-MCP-Agent-Type": PLAYGROUND_AGENT_TYPE,
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
      },
    );
  } catch (error) {
    throw new Error(transportErrorMessage(error));
  }

  const envelope = parseEnvelope(
    String(response.data),
    String(response.headers["content-type"] ?? ""),
  );
  if (envelope.error) {
    throw new Error(`JSON-RPC ${envelope.error.code}: ${envelope.error.message}`);
  }
  return { result: envelope.result as T, durationMs: Math.round(performance.now() - started) };
}

// ---------------------------------------------------------------------------
// Tools
// ---------------------------------------------------------------------------

export interface McpToolDef {
  name: string;
  description?: string;
  inputSchema?: Record<string, unknown>;
}

export interface McpToolResult {
  /** Text blocks joined — exactly what a model client would read. Dict
   * returns arrive as pretty-printed JSON text. */
  text: string;
  /** A *successful* JSON-RPC response reporting a failed tool call
   * (permission denial, bad arguments): the session stays alive, which is
   * why this is a flag and not a thrown error. */
  isError: boolean;
  /** Structured content when the tool returned a dict (SDK addition). */
  structured?: unknown;
  durationMs: number;
}

interface RawToolCallResult {
  content?: Array<{ type?: string; text?: string }>;
  isError?: boolean;
  structuredContent?: unknown;
}

export async function listMcpTools(mountPath: string): Promise<McpToolDef[]> {
  const { result } = await rpc<{ tools?: McpToolDef[] }>(mountPath, "tools/list", {});
  return result?.tools ?? [];
}

export async function callMcpTool(
  mountPath: string,
  name: string,
  args: Record<string, unknown>,
): Promise<McpToolResult> {
  const { result, durationMs } = await rpc<RawToolCallResult>(mountPath, "tools/call", {
    name,
    arguments: args,
  });
  const content = Array.isArray(result?.content) ? result.content : [];
  return {
    text: content
      .map((block) => block.text ?? "")
      .filter(Boolean)
      .join("\n\n"),
    isError: Boolean(result?.isError),
    structured: result?.structuredContent,
    durationMs,
  };
}

// ---------------------------------------------------------------------------
// Audit: what the agents did (mcp:agents:read)
// ---------------------------------------------------------------------------

/** The `detail` payload app/mcp/audit.py writes on every MCP row. */
export interface McpCallDetail {
  args?: Record<string, unknown>;
  duration_ms?: number;
  agent_type?: string;
  agent_id?: string;
}

export type McpCallRow = Omit<AuditLogRow, "detail"> & { detail: McpCallDetail };

export interface McpCallPage {
  items: McpCallRow[];
  total: number;
}

/** Recent MCP activity — tool calls AND gate rejections — from the
 * MCP-scoped endpoint. Not the generic audit listing: that one requires
 * `audit:read`, a permission the MCP operator deliberately does not need. */
export async function listMcpCalls(limit = 200, offset = 0): Promise<McpCallPage> {
  const { data } = await api.get<McpCallPage>("/mcp/calls", { params: { limit, offset } });
  return data;
}
