import type { ReactNode } from "react";

import { Button } from "cliver-playbook-app-basic/components/ui/button.tsx";
import { Input } from "cliver-playbook-app-basic/components/ui/input.tsx";

export function ChatShell({
  title,
  subtitle,
  children,
  footer,
}: {
  title: string;
  subtitle?: string;
  children: ReactNode;
  footer: ReactNode;
}) {
  return (
    <section className="mx-auto flex min-h-[calc(100vh-8rem)] w-full max-w-4xl flex-col gap-4 p-4 md:p-8">
      <header>
        <h1 className="text-2xl font-semibold md:text-3xl">{title}</h1>
        {subtitle ? (
          <p className="mt-1 text-sm text-muted-foreground">{subtitle}</p>
        ) : null}
      </header>
      <div className="flex-1 space-y-3 overflow-y-auto">{children}</div>
      <div className="sticky bottom-0 space-y-3 bg-background/95 pb-2 pt-2 backdrop-blur">
        {footer}
      </div>
    </section>
  );
}

export function ChatMessage({
  role,
  children,
}: {
  role: "user" | "assistant" | "system";
  children: ReactNode;
}) {
  const fromUser = role === "user";
  return (
    <div className={fromUser ? "flex justify-end" : "flex justify-start"}>
      <div
        className={
          fromUser
            ? "max-w-[85%] whitespace-pre-wrap rounded-2xl bg-primary px-4 py-3 text-sm text-primary-foreground"
            : "max-w-[85%] whitespace-pre-wrap rounded-2xl border bg-card px-4 py-3 text-sm text-card-foreground"
        }
      >
        {children}
      </div>
    </div>
  );
}

export function Composer({
  value,
  onChange,
  onSubmit,
  onStop,
  busy,
  placeholder,
  sendLabel,
  stopLabel,
}: {
  value: string;
  onChange: (value: string) => void;
  onSubmit: () => void;
  onStop: () => void;
  busy: boolean;
  placeholder: string;
  sendLabel: string;
  stopLabel: string;
}) {
  return (
    <form
      className="flex items-center gap-2"
      onSubmit={(event) => {
        event.preventDefault();
        onSubmit();
      }}
    >
      <Input
        aria-label={placeholder}
        placeholder={placeholder}
        value={value}
        onChange={(event) => onChange(event.target.value)}
      />
      {busy ? (
        <Button type="button" variant="outline" onClick={onStop}>
          {stopLabel}
        </Button>
      ) : (
        <Button type="submit" disabled={!value.trim()}>
          {sendLabel}
        </Button>
      )}
    </form>
  );
}

export function FeedbackButtons({
  value,
  onRate,
  helpfulLabel,
  notHelpfulLabel,
  thanksLabel,
  disabled = false,
}: {
  value: number | null;
  onRate: (rating: number) => void;
  helpfulLabel: string;
  notHelpfulLabel: string;
  thanksLabel: string;
  disabled?: boolean;
}) {
  if (value !== null) {
    return <p className="text-xs text-muted-foreground">{thanksLabel}</p>;
  }
  return (
    <div className="flex items-center gap-2">
      <Button
        type="button"
        size="sm"
        variant="outline"
        disabled={disabled}
        onClick={() => onRate(5)}
      >
        {helpfulLabel}
      </Button>
      <Button
        type="button"
        size="sm"
        variant="outline"
        disabled={disabled}
        onClick={() => onRate(1)}
      >
        {notHelpfulLabel}
      </Button>
    </div>
  );
}

export function ToolCallCard({
  name,
  arguments: args,
  result,
  error,
  resultLabel,
  errorLabel,
}: {
  name: string;
  arguments: Record<string, unknown>;
  result?: unknown;
  error?: boolean;
  resultLabel: string;
  errorLabel: string;
}) {
  return (
    <details
      className="rounded-lg border bg-muted/40 p-3 text-xs"
      open={Boolean(error)}
    >
      <summary className="cursor-pointer font-medium">{name}</summary>
      <pre className="mt-2 overflow-x-auto whitespace-pre-wrap text-muted-foreground">
        {formatValue(args)}
      </pre>
      {result !== undefined ? (
        <div className="mt-2 border-t pt-2">
          <p className="font-medium">{error ? errorLabel : resultLabel}</p>
          <pre className="mt-1 overflow-x-auto whitespace-pre-wrap">
            {formatValue(result)}
          </pre>
        </div>
      ) : null}
    </details>
  );
}

function formatValue(value: unknown): string {
  if (typeof value === "string") return value;
  try {
    return JSON.stringify(value, null, 2) ?? String(value);
  } catch {
    return String(value);
  }
}
