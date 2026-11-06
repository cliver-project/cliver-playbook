import { Component, type ErrorInfo, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { Button } from "cliver-playbook-app-basic/components/ui/button.tsx";

/** Arguments a custom fallback receives. */
export interface ErrorFallbackProps {
  /** The error thrown below the boundary. */
  error: Error;
  /** Clear the error and render the children again. */
  reset: () => void;
}

export interface ErrorBoundaryProps {
  children: ReactNode;
  /**
   * Replaces the built-in panel. A render function also receives the error
   * and the reset callback.
   */
  fallback?: ReactNode | ((props: ErrorFallbackProps) => ReactNode);
  /** Called before the fallback renders — wire an error tracker in here. */
  onError?: (error: Error, info: ErrorInfo) => void;
  /**
   * While the boundary is showing its fallback, a change to this value resets
   * it. `AppLayout` passes the current pathname, so navigating away from a
   * crashed page recovers without a full reload.
   */
  resetKey?: unknown;
}

interface ErrorBoundaryState {
  error: Error | null;
}

function DefaultErrorFallback({ reset }: ErrorFallbackProps) {
  const { t } = useTranslation();

  return (
    <div
      role="alert"
      className="border-destructive/40 bg-destructive/5 mx-auto max-w-lg rounded-lg border p-6 text-center"
    >
      <h1 className="text-lg font-semibold">{t("error.title")}</h1>
      <p className="text-muted-foreground mt-2 text-sm">{t("error.description")}</p>
      <div className="mt-4 flex items-center justify-center gap-2">
        <Button variant="outline" onClick={reset}>
          {t("error.retry")}
        </Button>
        <Button variant="ghost" onClick={() => window.location.reload()}>
          {t("error.reload")}
        </Button>
      </div>
    </div>
  );
}

/**
 * Route-level error boundary: catches render, lifecycle, and lazy-chunk
 * failures below it, then shows a recoverable panel instead of a blank page.
 *
 * A class component is required — React has no hook equivalent for
 * `componentDidCatch`. It does not catch errors in event handlers or rejected
 * promises outside rendering; handle those where they happen.
 *
 * `AppLayout` wraps its `<Outlet />` in this boundary, so every composed app
 * gets it for free. A page that wants its own scoped fallback can render
 * another boundary (or the app can wrap a subtree) with a custom `fallback`.
 */
export class ErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  state: ErrorBoundaryState = { error: null };

  static getDerivedStateFromError(error: Error): ErrorBoundaryState {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    // React logs uncaught errors itself; this line adds the component stack
    // context and gives an app hook (`onError`) to report it.
    console.error("Unhandled UI error", error, info);
    this.props.onError?.(error, info);
  }

  componentDidUpdate(prevProps: ErrorBoundaryProps) {
    if (this.state.error && prevProps.resetKey !== this.props.resetKey) {
      this.reset();
    }
  }

  reset = () => {
    this.setState({ error: null });
  };

  render() {
    const { error } = this.state;
    if (error === null) {
      return this.props.children;
    }
    const { fallback } = this.props;
    if (typeof fallback === "function") {
      return fallback({ error, reset: this.reset });
    }
    return fallback ?? <DefaultErrorFallback error={error} reset={this.reset} />;
  }
}

export default ErrorBoundary;
