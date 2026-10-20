import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

/**
 * Minimal centered chrome for standalone auth pages (login, change password,
 * OAuth callback/authorize). No app navigation: these pages exist precisely
 * because the user is not (yet) inside the application flow.
 */
export function AuthShell({
  title,
  subtitle,
  children,
}: {
  title: string;
  subtitle?: string;
  children: ReactNode;
}) {
  const { t } = useTranslation();
  return (
    <div className="bg-background flex min-h-svh items-center justify-center px-4">
      <div className="w-full max-w-sm">
        <p className="text-muted-foreground mb-6 text-center text-sm">{t("app.title")}</p>
        <div className="bg-card text-card-foreground rounded-xl border p-6 shadow-sm">
          <h1 className="text-center text-lg font-semibold">{title}</h1>
          {subtitle ? <p className="text-muted-foreground mt-1 text-center text-sm">{subtitle}</p> : null}
          <div className="mt-6">{children}</div>
        </div>
      </div>
    </div>
  );
}
