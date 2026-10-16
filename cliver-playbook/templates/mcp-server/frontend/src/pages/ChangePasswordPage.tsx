import { useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";

import { useAuth } from "@/components/auth/AuthContext";
import { AuthShell } from "@/components/auth/AuthShell";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { apiErrorMessage } from "@/api/client";
import { changePassword } from "@/api/auth";

/**
 * Self-service password change — also the landing page for accounts the
 * server flagged must_change_password (fresh accounts, admin-forced resets).
 *
 * On success the backend revokes EVERY token for the user and returns one
 * fresh web token; adopting it keeps this browser signed in while every other
 * session (other tabs, other devices, static tokens) drops dead.
 */
export default function ChangePasswordPage() {
  const { t } = useTranslation();
  const { status, user, adoptToken } = useAuth();
  const navigate = useNavigate();
  const [oldPassword, setOldPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [pending, setPending] = useState(false);

  const gated = user?.must_change_password ?? false;

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    if (newPassword !== confirm) {
      toast.error(t("auth.passwordsDoNotMatch"));
      return;
    }
    setPending(true);
    try {
      const result = await changePassword(oldPassword, newPassword);
      await adoptToken(result.token);
      toast.success(t("auth.passwordChanged"));
      navigate("/", { replace: true });
    } catch (error) {
      toast.error(apiErrorMessage(error));
    } finally {
      setPending(false);
    }
  }

  // Anonymous visitors have no token to change; the gate only makes sense
  // with a session. (The interceptor sends tokenless users to /login on any
  // authenticated call anyway — this is the direct-navigation case.)
  if (status === "anonymous") {
    return (
      <AuthShell title={t("auth.changePasswordTitle")}>
        <p className="text-muted-foreground text-center text-sm">{t("auth.needSession")}</p>
        <Button asChild variant="outline" className="mt-4 w-full">
          <Link to="/login">{t("auth.signIn")}</Link>
        </Button>
      </AuthShell>
    );
  }

  return (
    <AuthShell
      title={t("auth.changePasswordTitle")}
      subtitle={gated ? t("auth.changePasswordForced") : undefined}
    >
      <form onSubmit={handleSubmit} className="grid gap-4">
        <div className="grid gap-2">
          <Label htmlFor="old">{t("auth.currentPassword")}</Label>
          <Input
            id="old"
            type="password"
            autoComplete="current-password"
            value={oldPassword}
            onChange={(e) => setOldPassword(e.target.value)}
            required
            autoFocus
          />
        </div>
        <div className="grid gap-2">
          <Label htmlFor="new">{t("auth.newPassword")}</Label>
          <Input
            id="new"
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
          <Label htmlFor="confirm">{t("auth.confirmPassword")}</Label>
          <Input
            id="confirm"
            type="password"
            autoComplete="new-password"
            value={confirm}
            onChange={(e) => setConfirm(e.target.value)}
            required
            minLength={8}
          />
        </div>
        <Button type="submit" disabled={pending}>
          {pending ? t("common.pending") : t("auth.changePasswordSubmit")}
        </Button>
      </form>
    </AuthShell>
  );
}
