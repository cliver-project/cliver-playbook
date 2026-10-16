import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";

import { useAuth } from "@/components/auth/AuthContext";
import { AuthShell } from "@/components/auth/AuthShell";
import { Button } from "@/components/ui/button";

/**
 * Landing page for the OIDC login redirect: the backend sends the session
 * token in the URL fragment (`#token=...&must_change_password=...`), which
 * browsers never transmit to any server — the SPA is the only reader.
 *
 * On failure the fragment carries `#error=<reason>` instead. Either way the
 * fragment is scrubbed from history immediately: pressing back must not
 * replay a (stale, possibly still-valid) token into the address bar.
 */
export default function OAuthCallbackPage() {
  const { t } = useTranslation();
  const { adoptToken } = useAuth();
  const navigate = useNavigate();

  // Parse the fragment once, lazily, during the first render (an effect would
  // mean a pointless intermediate frame). Only the side effects — scrubbing
  // the fragment, adopting the token — belong in the effect below.
  const [handoff] = useState(() => {
    const params = new URLSearchParams(window.location.hash.slice(1));
    return {
      token: params.get("token"),
      mustChange: params.get("must_change_password") === "true",
      error: params.get("error"),
    };
  });
  // Null while a token is being adopted; a reason string once it failed.
  const [error, setError] = useState<string | null>(
    handoff.token ? null : (handoff.error ?? "missing_token"),
  );

  useEffect(() => {
    // Scrub first: whatever happens next, the fragment must not survive.
    window.history.replaceState(null, "", window.location.pathname);

    if (handoff.token) {
      void adoptToken(handoff.token).then((user) => {
        if (user) {
          navigate(user.must_change_password || handoff.mustChange ? "/change-password" : "/", {
            replace: true,
          });
        } else {
          setError("invalid_token");
        }
      });
    }
  }, [adoptToken, navigate, handoff.token, handoff.mustChange]);

  if (error) {
    return (
      <AuthShell title={t("auth.oauthCallbackTitle")}>
        <p className="text-muted-foreground text-center text-sm">
          {t(`auth.oauthErrors.${error}`, { defaultValue: t("auth.oauthErrors.unknown") })}
        </p>
        <Button asChild variant="outline" className="mt-4 w-full">
          <Link to="/login">{t("auth.backToLogin")}</Link>
        </Button>
      </AuthShell>
    );
  }

  return (
    <AuthShell title={t("auth.oauthCallbackTitle")}>
      <p className="text-muted-foreground animate-pulse text-center text-sm">
        {t("auth.completingSignIn")}
      </p>
    </AuthShell>
  );
}
