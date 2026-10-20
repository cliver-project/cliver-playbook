import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { useAuth } from "cliver-playbook-app-user/components/auth/AuthContext.tsx";

/**
 * Route-level permission gate for UI affordances.
 *
 * The server rejects unauthorized calls regardless (every admin endpoint
 * declares require_perm); this component just avoids rendering pages the
 * viewer cannot meaningfully use. An explicit "no access" panel beats a
 * page full of disabled buttons and 403 toasts.
 */
export function RequirePerm({ code, children }: { code: string; children: ReactNode }) {
  const { hasPerm } = useAuth();
  const { t } = useTranslation();

  if (!hasPerm(code)) {
    return (
      <div className="text-muted-foreground flex min-h-40 flex-col items-center justify-center gap-2 py-16">
        <p className="text-foreground font-medium">{t("auth.noAccess")}</p>
        <p className="text-sm">{t("auth.noAccessHint", { code })}</p>
      </div>
    );
  }
  return <>{children}</>;
}
