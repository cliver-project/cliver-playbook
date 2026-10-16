import { useState, type FormEvent } from "react";
import { useQuery } from "@tanstack/react-query";
import { useLocation, useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";

import { useAuth } from "@/components/auth/AuthContext";
import { AuthShell } from "@/components/auth/AuthShell";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { apiErrorMessage } from "@/api/client";
import { listOAuthProviders, oauthLoginUrl } from "@/api/auth";

/**
 * Password session login, plus SSO buttons for every configured OIDC
 * provider. The provider list is fetched live: when no provider is configured
 * the SSO section does not render at all.
 *
 * After login the router decides the destination: users the server flagged
 * must_change_password go straight to the gate page, everyone else continues
 * to the page that originally linked here (or home).
 */
export default function LoginPage() {
  const { t } = useTranslation();
  const { login } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [pending, setPending] = useState(false);

  const from = (location.state as { from?: string } | null)?.from ?? "/";

  const providers = useQuery({
    queryKey: ["oauthProviders"],
    queryFn: listOAuthProviders,
    // An unreachable backend here must not wedge the form.
    retry: false,
    staleTime: 5 * 60_000,
  });

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    setPending(true);
    try {
      const user = await login(username, password);
      navigate(user.must_change_password ? "/change-password" : from, { replace: true });
    } catch (error) {
      toast.error(apiErrorMessage(error));
    } finally {
      setPending(false);
    }
  }

  return (
    <AuthShell title={t("auth.loginTitle")} subtitle={t("auth.loginSubtitle")}>
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
        <Button type="submit" disabled={pending}>
          {pending ? t("common.pending") : t("auth.signIn")}
        </Button>
      </form>

      {providers.data && providers.data.length > 0 ? (
        <>
          <div className="my-6 flex items-center gap-3">
            <div className="bg-border h-px flex-1" />
            <span className="text-muted-foreground text-xs">{t("auth.orContinueWith")}</span>
            <div className="bg-border h-px flex-1" />
          </div>
          <div className="grid gap-2">
            {providers.data.map((provider) => (
              <Button
                key={provider.key}
                type="button"
                variant="outline"
                // Full tab navigation: OIDC is a redirect dance across origins.
                onClick={() => window.location.assign(oauthLoginUrl(provider.key))}
              >
                {t("auth.ssoWith", { provider: provider.label })}
              </Button>
            ))}
          </div>
        </>
      ) : null}
    </AuthShell>
  );
}
