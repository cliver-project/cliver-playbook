import { useState, type FormEvent } from "react";
import { useQuery } from "@tanstack/react-query";
import { useSearchParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";

import { AuthShell } from "cliver-playbook-app-user/components/auth/AuthShell.tsx";
import { Badge } from "cliver-playbook-app-basic/components/ui/badge.tsx";
import { Button } from "cliver-playbook-app-basic/components/ui/button.tsx";
import { Input } from "cliver-playbook-app-basic/components/ui/input.tsx";
import { Label } from "cliver-playbook-app-basic/components/ui/label.tsx";
import { apiErrorMessage } from "cliver-playbook-app-basic/api/client.ts";
import { fetchAuthorizeInfo, submitAuthorize } from "cliver-playbook-app-user/api/auth.ts";

/**
 * The OAuth 2.1 authorize page (ADR-0005): an agent (MCP client, CLI, ...)
 * that wants access is redirected here with a signed, short-lived blob in
 * ?oauth=. The page shows WHICH client asks for WHICH scopes, collects the
 * user's credentials once, and hands the resulting code+state redirect URL
 * back to the agent's callback by navigating the whole tab.
 *
 * The blob — not this form — carries scopes/challenge/redirect: the server
 * verifies the signature and builds the redirect exclusively from it, so
 * nothing the browser submits can tamper with the grant.
 */
export default function OAuthAuthorizePage() {
  const { t } = useTranslation();
  const [searchParams] = useSearchParams();
  const blob = searchParams.get("oauth") ?? "";
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [pending, setPending] = useState(false);

  const info = useQuery({
    queryKey: ["authorizeInfo", blob],
    queryFn: () => fetchAuthorizeInfo(blob),
    enabled: blob.length > 0,
    retry: false, // an expired blob will not heal; show the error card
  });

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    setPending(true);
    try {
      const redirectUrl = await submitAuthorize(blob, username, password);
      window.location.assign(redirectUrl);
    } catch (error) {
      toast.error(apiErrorMessage(error));
      setPending(false);
    }
  }

  if (!blob) {
    return (
      <AuthShell title={t("auth.authorizeTitle")}>
        <p className="text-muted-foreground text-center text-sm">{t("auth.authorizeMissingBlob")}</p>
      </AuthShell>
    );
  }

  if (info.isError) {
    return (
      <AuthShell title={t("auth.authorizeTitle")}>
        <p className="text-muted-foreground text-center text-sm">{t("auth.authorizeExpired")}</p>
      </AuthShell>
    );
  }

  return (
    <AuthShell title={t("auth.authorizeTitle")} subtitle={t("auth.authorizeSubtitle")}>
      <div className="mb-6 space-y-2 text-center">
        {info.data ? (
          <>
            <p className="text-sm">
              <span className="text-foreground font-medium">{info.data.client_name}</span>
            </p>
            <div className="flex flex-wrap items-center justify-center gap-1">
              {info.data.scopes.length > 0 ? (
                info.data.scopes.map((scope) => <Badge key={scope} variant="secondary">{scope}</Badge>)
              ) : (
                <span className="text-muted-foreground text-xs">{t("auth.authorizeNoScopes")}</span>
              )}
            </div>
          </>
        ) : (
          <p className="text-muted-foreground animate-pulse text-sm">{t("common.loading")}</p>
        )}
      </div>

      <form onSubmit={handleSubmit} className="grid gap-4">
        <div className="grid gap-2">
          <Label htmlFor="username">{t("auth.username")}</Label>
          <Input
            id="username"
            autoComplete="username"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            required
            autoFocus
          />
        </div>
        <div className="grid gap-2">
          <Label htmlFor="password">{t("auth.password")}</Label>
          <Input
            id="password"
            type="password"
            autoComplete="current-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
          />
        </div>
        <Button type="submit" disabled={pending || !info.data}>
          {pending ? t("common.pending") : t("auth.authorizeSubmit")}
        </Button>
        <p className="text-muted-foreground text-center text-xs">{t("auth.authorizeHint")}</p>
      </form>
    </AuthShell>
  );
}
