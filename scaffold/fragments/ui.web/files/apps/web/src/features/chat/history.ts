import type { RunAgentResult, RunHandoff, RunPlanStep } from "../../ui";
import type { AgentEvent, AgentSessionDetail } from "./api";

const SESSION_KEY = "cliver-agent-session";

export type HistoryMessage = {
  role: "user" | "assistant";
  text: string;
};

export type SessionHistory = {
  messages: HistoryMessage[];
  plan: RunPlanStep[];
  results: RunAgentResult[];
  handoffs: RunHandoff[];
};

/**
 * Rebuild the conversation and the latest run inspector from stored events.
 * A run without streamed deltas still contributes its final agent.result.
 */
export function sessionHistory(detail: AgentSessionDetail): SessionHistory {
  const messages: HistoryMessage[] = [];
  const runs = detail.runs.map((run) => ({
    ...run,
    events: run.events as unknown as AgentEvent[],
  }));

  for (const run of runs) {
    messages.push({ role: "user", text: run.message });
    const text = run.events
      .filter((event) => event.type === "message.delta")
      .map((event) => event.delta ?? "")
      .join("");
    const final = [...run.events].reverse().find((event) => event.type === "agent.result");
    messages.push({ role: "assistant", text: text || String(final?.message ?? "") });
  }

  const latest = runs.at(-1)?.events ?? [];
  const planEvent = [...latest].reverse().find((event) => event.type === "coordinator.plan");
  return {
    messages,
    plan: (planEvent?.steps ?? []).map((step) => ({
      name: String(step.name ?? "general"),
      confidence: step.confidence,
      parallelGroup: step.parallel_group ?? null,
    })),
    results: latest
      .filter((event) => event.type === "agent.result")
      .map((event) => ({ agent: event.agent ?? "general", message: event.message })),
    handoffs: latest
      .filter((event) => event.type === "agent.handoff")
      .map((event) => ({
        from: event.agent ?? "unknown",
        to: event.target ?? "unknown",
        reason: event.reason,
        depth: event.depth,
      })),
  };
}

export function currentSessionId(): string {
  try {
    const stored = localStorage.getItem(SESSION_KEY);
    if (stored && stored.length <= 200) return stored;
  } catch {
    // Storage can be unavailable in hardened browser contexts.
  }
  return newSessionId();
}

export function newSessionId(): string {
  const id =
    globalThis.crypto?.randomUUID?.() ??
    `session-${Date.now()}-${Math.random().toString(16).slice(2)}`;
  rememberSessionId(id);
  return id;
}

export function rememberSessionId(sessionId: string): void {
  try {
    localStorage.setItem(SESSION_KEY, sessionId);
  } catch {
    // The in-memory session id still works for this tab.
  }
}
