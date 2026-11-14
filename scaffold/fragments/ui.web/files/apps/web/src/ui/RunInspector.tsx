export type RunPlanStep = {
  name: string;
  confidence?: number;
  parallelGroup?: number | null;
};

export type RunHandoff = {
  from: string;
  to: string;
  reason?: string;
  depth?: number;
};

export type RunAgentResult = {
  agent: string;
  message?: string;
};

/**
 * Collapsible, read-only view of the current multi-agent run. It exposes the
 * plan, the agents that produced results and any direct handoffs without
 * changing chat flow; replace it through the UI seam when a project has its
 * own run inspector.
 */
export function RunInspector({
  title,
  planLabel,
  agentsLabel,
  handoffsLabel,
  parallelLabel,
  emptyLabel,
  steps,
  results,
  handoffs,
}: {
  title: string;
  planLabel: string;
  agentsLabel: string;
  handoffsLabel: string;
  parallelLabel: string;
  emptyLabel: string;
  steps: RunPlanStep[];
  results: RunAgentResult[];
  handoffs: RunHandoff[];
}) {
  const hasDetails = steps.length > 0 || results.length > 0 || handoffs.length > 0;
  return (
    <details className="rounded-lg border bg-muted/30 p-3 text-sm">
      <summary className="cursor-pointer select-none font-medium">
        {title}
        {steps.length > 0 ? ` (${steps.length})` : null}
      </summary>
      <div className="mt-3 space-y-3">
        {!hasDetails ? (
          <p className="text-muted-foreground">{emptyLabel}</p>
        ) : null}
        {steps.length > 0 ? (
          <section aria-label={planLabel}>
            <h3 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
              {planLabel}
            </h3>
            <ol className="mt-1 space-y-1">
              {steps.map((step, index) => (
                <li key={`${index}-${step.name}`} className="flex flex-wrap items-center gap-2">
                  <span className="font-mono text-xs">
                    {index + 1}. {step.name}
                  </span>
                  {step.parallelGroup != null ? (
                    <span className="rounded-full border px-2 py-0.5 text-[11px] text-muted-foreground">
                      {parallelLabel} {step.parallelGroup}
                    </span>
                  ) : null}
                </li>
              ))}
            </ol>
          </section>
        ) : null}
        {results.length > 0 ? (
          <section aria-label={agentsLabel}>
            <h3 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
              {agentsLabel}
            </h3>
            <ul className="mt-1 space-y-1">
              {results.map((result, index) => (
                <li key={`${index}-${result.agent}`} className="text-xs">
                  <span className="font-mono" title={result.message}>
                    {result.agent}
                  </span>
                </li>
              ))}
            </ul>
          </section>
        ) : null}
        {handoffs.length > 0 ? (
          <section aria-label={handoffsLabel}>
            <h3 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
              {handoffsLabel}
            </h3>
            <ul className="mt-1 space-y-1">
              {handoffs.map((handoff, index) => (
                <li key={`${index}-${handoff.from}-${handoff.to}`} className="text-xs">
                  <span className="font-mono">
                    {handoff.from} → {handoff.to}
                  </span>
                  {handoff.reason ? (
                    <span className="text-muted-foreground"> — {handoff.reason}</span>
                  ) : null}
                </li>
              ))}
            </ul>
          </section>
        ) : null}
      </div>
    </details>
  );
}
