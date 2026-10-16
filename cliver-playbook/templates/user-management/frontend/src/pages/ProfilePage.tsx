import { useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";

import { useAuth } from "@/components/auth/AuthContext";
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
import { changePassword, updateProfile } from "@/api/auth";

/**
 * Self-service profile page: the caller's own contact details plus an inline
 * password change.
 *
 * Two independent forms on purpose — editing an email should not require
 * re-typing a password, and a password rotation should not silently re-send
 * (possibly stale) contact fields. The password half mirrors
 * ChangePasswordPage: the backend revokes every token and returns one fresh
 * web token, which adoptToken() swaps in so THIS browser stays signed in.
 *
 * Username is shown read-only: it is the stable identity handle and only
 * admins manage it (see ProfileUpdate on the backend for the same boundary).
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
    </div>
  );
}
