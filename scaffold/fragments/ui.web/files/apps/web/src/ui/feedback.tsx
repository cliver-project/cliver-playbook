import type { ReactNode } from "react";

export function EmptyState({
  title,
  body,
  action,
}: {
  title: string;
  body?: string;
  action?: ReactNode;
}) {
  return (
    <div className="flex flex-col items-center gap-2 rounded-lg border border-dashed p-8 text-center">
      <p className="font-medium">{title}</p>
      {body ? <p className="text-sm text-muted-foreground">{body}</p> : null}
      {action}
    </div>
  );
}

export function LoadingState({ label = "Loading…" }: { label?: string }) {
  return (
    <p role="status" className="p-4 text-sm text-muted-foreground">
      {label}
    </p>
  );
}

export function ErrorState({ message }: { message: string }) {
  return <p className="p-4 text-sm text-destructive">{message}</p>;
}
