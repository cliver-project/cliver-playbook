import { useEffect, useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";

import { useAuth } from "@/components/auth/AuthContext";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { apiErrorMessage } from "@/api/client";
import {
  changePassword,
  listLinkedIdentities,
  listOAuthProviders,
  startIdentityLink,
  unlinkIdentity,
  updateProfile,
  type LinkedIdentity,
} from "@/api/auth";

/**
 * Self-service profile page: the caller's own contact details, an inline
 * password change, and linked external identities.
 *
 * Two independent forms on purpose — editing an email should not require
 * re-typing a password, and a password rotation should not silently re-send
 * (possibly stale) contact fields. The password half mirrors
 * ChangePasswordPage: the backend revokes every token and returns one fresh
 * web token, which adoptToken() swaps in so THIS browser stays signed in.
 *
 * Username is shown read-only: it is the stable identity handle and only
 * admins manage it (see ProfileUpdate on the backend for the same boundary).
 *
 * The linked-accounts card is the landing point of the identity-link redirect
 * chain: the backend sends the outcome in the URL fragment
 * (`#linked=<provider>` / `#link_error=<reason>`), which — exactly like the
 * login callback's `#token=` — never reaches any server. It is parsed once
 * and scrubbed from history immediately so back/reload cannot replay it.
 */
export default function ProfilePage() {
  const { t } = useTranslation();
  const { user, refresh, adoptToken } = useAuth();

  // --- contact details form ------------------------------------------------
  const [displayName, setDisplayName] = useState(user?.display_name ?? "");
  const [email, setEmail] = useState(user?.email ?? "");
  const [phone, setPhone] = useState(user?.phone ?? "");
  const [savingProfile, setSavingProfile] = useState(false);

  async function handleProfileSubmit(event: FormEvent) {
    event.preventDefault();
    setSavingProfile(true);
    try {
      // Empty strings clear email/phone server-side; display_name is required.
      await updateProfile({
        display_name: displayName.trim(),
        email: email.trim(),
        phone: phone.trim(),
      });
      await refresh(); // header/avatar name reflects the change immediately
      toast.success(t("profile.saved"));
    } catch (error) {
      toast.error(apiErrorMessage(error));
    } finally {
      setSavingProfile(false);
    }
  }

  // --- password form ---------------------------------------------------------
  const [oldPassword, setOldPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [savingPassword, setSavingPassword] = useState(false);

  async function handlePasswordSubmit(event: FormEvent) {
    event.preventDefault();
    if (newPassword !== confirm) {
      toast.error(t("auth.passwordsDoNotMatch"));
      return;
    }
    setSavingPassword(true);
    try {
      const result = await changePassword(oldPassword, newPassword);
      await adoptToken(result.token);
      setOldPassword("");
      setNewPassword("");
      setConfirm("");
      toast.success(t("auth.passwordChanged"));
    } catch (error) {
      toast.error(apiErrorMessage(error));
    } finally {
      setSavingPassword(false);
    }
  }

  // --- linked accounts card --------------------------------------------------
  // Outcome of the link redirect chain, parsed lazily on first render and
  // consumed (scrubbed + toasted) in the effect below — see OAuthCallbackPage
  // for the same fragment-discipline pattern.
  const [handoff] = useState(() => {
    const params = new URLSearchParams(window.location.hash.slice(1));
    return { linked: params.get("linked"), linkError: params.get("link_error") };
  });

  useEffect(() => {
    if (!handoff.linked && !handoff.linkError) return;
    // Scrub first: whatever happens next, the fragment must not survive.
    window.history.replaceState(null, "", window.location.pathname);
    if (handoff.linked) {
      toast.success(t("profile.linkedAccounts.linkedToast", { provider: handoff.linked }));
    } else if (handoff.linkError) {
      toast.error(
        t(`profile.linkedAccounts.linkErrors.${handoff.linkError}`, {
          defaultValue: t("profile.linkedAccounts.linkErrors.unknown"),
        }),
      );
    }
    // Runs once per mount by design — the fragment is gone after this, so
    // `handoff`/`t` cannot change meaningfully for a second run.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const queryClient = useQueryClient();
  const identities = useQuery({ queryKey: ["identities"], queryFn: listLinkedIdentities });
  // Enabled providers only; same query key as the login page's SSO buttons.
  const providers = useQuery({
    queryKey: ["oauthProviders"],
    queryFn: listOAuthProviders,
    staleTime: 60_000,
  });
  const linkedKeys = new Set((identities.data ?? []).map((row) => row.provider));
  // Connect buttons: configured AND enabled AND not already linked. Disabled
  // presets contribute nothing server-side, so the provider list is the truth.
  const connectable = (providers.data ?? []).filter((p) => !linkedKeys.has(p.key));

  const [unlinking, setUnlinking] = useState<LinkedIdentity | null>(null);

  const link = useMutation({
    mutationFn: (providerKey: string) => startIdentityLink(providerKey),
    // Full-page navigation: the redirect chain must leave the SPA for the
    // IdP and come back to the backend callback, then to /profile#linked=…
    onSuccess: (redirectUrl) => window.location.assign(redirectUrl),
    onError: (error) => toast.error(apiErrorMessage(error)),
  });

  const unlink = useMutation({
    mutationFn: (id: number) => unlinkIdentity(id),
    onSuccess: () => {
      toast.success(t("profile.linkedAccounts.unlinkedToast"));
      setUnlinking(null);
      void queryClient.invalidateQueries({ queryKey: ["identities"] });
    },
    // A 409 (last credential) or 404 arrives with the server's message.
    onError: (error) => toast.error(apiErrorMessage(error)),
  });

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-semibold tracking-tight">{t("profile.title")}</h1>

      <Card>
        <CardHeader>
          <CardTitle>{t("profile.infoTitle")}</CardTitle>
          <CardDescription>{t("profile.infoDescription")}</CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleProfileSubmit} className="grid gap-4">
            <div className="grid gap-2">
              <Label htmlFor="profile-username">{t("admin.users.username")}</Label>
              <Input id="profile-username" value={user?.username ?? ""} disabled />
              <p className="text-muted-foreground text-xs">{t("profile.usernameHint")}</p>
            </div>
            <div className="grid gap-2">
              <Label htmlFor="profile-display-name">{t("admin.users.displayName")}</Label>
              <Input
                id="profile-display-name"
                value={displayName}
                onChange={(e) => setDisplayName(e.target.value)}
                required
                minLength={1}
                maxLength={128}
              />
            </div>
            <div className="grid gap-2">
              <Label htmlFor="profile-email">{t("admin.users.email")}</Label>
              <Input
                id="profile-email"
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                maxLength={255}
              />
            </div>
            <div className="grid gap-2">
              <Label htmlFor="profile-phone">{t("admin.users.phone")}</Label>
              <Input
                id="profile-phone"
                type="tel"
                value={phone}
                onChange={(e) => setPhone(e.target.value)}
                maxLength={32}
              />
              <p className="text-muted-foreground text-xs">{t("admin.users.phoneHint")}</p>
            </div>
            <div>
              <Button type="submit" disabled={savingProfile}>
                {savingProfile ? t("common.pending") : t("common.save")}
              </Button>
            </div>
          </form>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>{t("profile.passwordTitle")}</CardTitle>
          <CardDescription>{t("profile.passwordDescription")}</CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={handlePasswordSubmit} className="grid gap-4">
            <div className="grid gap-2">
              <Label htmlFor="profile-old-password">{t("auth.currentPassword")}</Label>
              <Input
                id="profile-old-password"
                type="password"
                autoComplete="current-password"
                value={oldPassword}
                onChange={(e) => setOldPassword(e.target.value)}
                required
              />
            </div>
            <div className="grid gap-2">
              <Label htmlFor="profile-new-password">{t("auth.newPassword")}</Label>
              <Input
                id="profile-new-password"
                type="password"
                autoComplete="new-password"
                value={newPassword}
                onChange={(e) => setNewPassword(e.target.value)}
                required
                minLength={8}
              />
              <p className="text-muted-foreground text-xs">{t("auth.passwordHint")}</p>
            </div>
            <div className="grid gap-2">
              <Label htmlFor="profile-confirm-password">{t("auth.confirmPassword")}</Label>
              <Input
                id="profile-confirm-password"
                type="password"
                autoComplete="new-password"
                value={confirm}
                onChange={(e) => setConfirm(e.target.value)}
                required
                minLength={8}
              />
            </div>
            <div>
              <Button type="submit" disabled={savingPassword}>
                {savingPassword ? t("common.pending") : t("auth.changePasswordSubmit")}
              </Button>
            </div>
          </form>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>{t("profile.linkedAccounts.title")}</CardTitle>
          <CardDescription>{t("profile.linkedAccounts.description")}</CardDescription>
        </CardHeader>
        <CardContent className="grid gap-4">
          {identities.isLoading ? (
            <p className="text-muted-foreground text-sm">{t("common.loading")}</p>
          ) : identities.isError ? (
            <p className="text-muted-foreground text-sm">{t("common.error")}</p>
          ) : (identities.data ?? []).length === 0 ? (
            <p className="text-muted-foreground text-sm">{t("profile.linkedAccounts.empty")}</p>
          ) : (
            <ul className="divide-y">
              {(identities.data ?? []).map((row) => (
                <li key={row.id} className="flex items-center justify-between gap-4 py-3 first:pt-0 last:pb-0">
                  <div className="min-w-0">
                    <p className="text-sm font-medium">{row.provider_label}</p>
                    <p className="text-muted-foreground truncate text-xs">
                      {/* Email snapshot; display name is the fallback for
                          providers that do not return one (GitHub nulls). */}
                      {row.email || row.display_name || row.provider}
                      {" · "}
                      {t("profile.linkedAccounts.linkedOn", {
                        date: new Date(row.linked_at).toLocaleDateString(),
                      })}
                    </p>
                  </div>
                  <div className="flex shrink-0 items-center gap-2">
                    {row.is_last_credential ? (
                      <span className="text-muted-foreground text-xs">
                        {t("profile.linkedAccounts.lastCredentialHint")}
                      </span>
                    ) : null}
                    <Button
                      variant="outline"
                      size="sm"
                      disabled={row.is_last_credential}
                      onClick={() => setUnlinking(row)}
                    >
                      {t("profile.linkedAccounts.unlink")}
                    </Button>
                  </div>
                </li>
              ))}
            </ul>
          )}

          {connectable.length > 0 ? (
            <div className="flex flex-wrap gap-2">
              {connectable.map((provider) => (
                <Button
                  key={provider.key}
                  variant="outline"
                  size="sm"
                  disabled={link.isPending}
                  onClick={() => link.mutate(provider.key)}
                >
                  {link.isPending ? t("common.pending") : t("profile.linkedAccounts.connect", { provider: provider.label })}
                </Button>
              ))}
            </div>
          ) : null}
        </CardContent>
      </Card>

      <ConfirmDialog
        open={unlinking !== null}
        onOpenChange={(open) => !open && setUnlinking(null)}
        title={t("profile.linkedAccounts.unlinkTitle", {
          provider: unlinking?.provider_label ?? "",
        })}
        description={t("profile.linkedAccounts.unlinkConfirm")}
        confirmLabel={t("profile.linkedAccounts.unlink")}
        pending={unlink.isPending}
        onConfirm={() => unlinking && unlink.mutate(unlinking.id)}
      />
    </div>
  );
}
