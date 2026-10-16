import { useEffect, useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";

import { useAuth } from "cliver-playbook-app-user/components/auth/AuthContext.tsx";
import { ConfirmDialog } from "cliver-playbook-app-basic/components/ConfirmDialog.tsx";
import { Badge } from "cliver-playbook-app-basic/components/ui/badge.tsx";
import { Button } from "cliver-playbook-app-basic/components/ui/button.tsx";
import { Checkbox } from "cliver-playbook-app-basic/components/ui/checkbox.tsx";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "cliver-playbook-app-basic/components/ui/dialog.tsx";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "cliver-playbook-app-basic/components/ui/dropdown-menu.tsx";
import { Input } from "cliver-playbook-app-basic/components/ui/input.tsx";
import { Label } from "cliver-playbook-app-basic/components/ui/label.tsx";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "cliver-playbook-app-basic/components/ui/table.tsx";
import { apiErrorMessage } from "cliver-playbook-app-basic/api/client.ts";
import {
  createUser,
  deleteUser,
  forceLogout,
  listRoles,
  listUsers,
  resetPassword,
  type CurrentUser,
  type UserCreateInput,
  type UserUpdateInput,
  updateUser,
} from "cliver-playbook-app-user/api/auth.ts";

/**
 * User administration: searchable table plus create/edit dialogs and the
 * destructive/administrative actions (reset password, force logout, delete).
 *
 * Every action button is hidden by `hasPerm` — display gating only; the
 * server rejects unauthorized calls regardless of what the UI renders. The
 * backend additionally refuses self-delete/self-deactivate/self-demote and
 * last-admin removal, so those errors surface as toasts straight from the
 * API's message.
 */

/** Fields shared by the create and edit dialogs. */
interface UserFormState {
  username: string;
  password: string;
  display_name: string;
  email: string;
  phone: string;
  is_active: boolean;
  role_ids: number[];
}

const EMPTY_FORM: UserFormState = {
  username: "",
  password: "",
  display_name: "",
  email: "",
  phone: "",
  is_active: true,
  role_ids: [],
};

export default function UsersPage() {
  const { t } = useTranslation();
  const { hasPerm } = useAuth();
  const queryClient = useQueryClient();

  // Search box: local text immediately, server query debounced to 300ms so
  // typing "administrator" does not fire eight requests.
  const [search, setSearch] = useState("");
  const [query, setQuery] = useState("");
  useEffect(() => {
    const timer = setTimeout(() => setQuery(search.trim()), 300);
    return () => clearTimeout(timer);
  }, [search]);

  const users = useQuery({ queryKey: ["users", query], queryFn: () => listUsers(query || undefined) });
  const roles = useQuery({ queryKey: ["roles"], queryFn: listRoles, staleTime: 60_000 });

  const invalidate = () => queryClient.invalidateQueries({ queryKey: ["users"] });

  const [creating, setCreating] = useState(false);
  const [editing, setEditing] = useState<CurrentUser | null>(null);
  const [resetting, setResetting] = useState<CurrentUser | null>(null);
  const [evicting, setEvicting] = useState<CurrentUser | null>(null);
  const [deleting, setDeleting] = useState<CurrentUser | null>(null);

  const remove = useMutation({
    mutationFn: (id: number) => deleteUser(id),
    onSuccess: () => {
      toast.success(t("admin.users.deleted"));
      setDeleting(null);
      void invalidate();
    },
    onError: (error) => toast.error(apiErrorMessage(error)),
  });

  const evict = useMutation({
    mutationFn: (id: number) => forceLogout(id),
    onSuccess: () => {
      toast.success(t("admin.users.loggedOutEverywhere"));
      setEvicting(null);
      void invalidate();
    },
    onError: (error) => toast.error(apiErrorMessage(error)),
  });

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3">
        <h1 className="text-2xl font-semibold tracking-tight">{t("admin.users.title")}</h1>
        <div className="ml-auto flex items-center gap-2">
          <Input
            placeholder={t("common.search")}
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="w-56"
          />
          {hasPerm("user:create") ? (
            <Button onClick={() => setCreating(true)}>{t("admin.users.create")}</Button>
          ) : null}
        </div>
      </div>

      <div className="rounded-lg border">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>{t("admin.users.username")}</TableHead>
              <TableHead>{t("admin.users.displayName")}</TableHead>
              <TableHead>{t("admin.users.email")}</TableHead>
              <TableHead>{t("admin.users.phone")}</TableHead>
              <TableHead>{t("admin.users.roles")}</TableHead>
              <TableHead>{t("admin.users.status")}</TableHead>
              <TableHead className="w-10" />
            </TableRow>
          </TableHeader>
          <TableBody>
            {users.isLoading ? (
              <TableRow>
                <TableCell colSpan={7} className="text-muted-foreground">
                  {t("common.loading")}
                </TableCell>
              </TableRow>
            ) : users.data && users.data.length > 0 ? (
              users.data.map((user) => (
                <TableRow key={user.id}>
                  <TableCell className="font-medium">{user.username}</TableCell>
                  <TableCell>{user.display_name}</TableCell>
                  <TableCell className="text-muted-foreground">{user.email ?? "—"}</TableCell>
                  <TableCell className="text-muted-foreground">{user.phone ?? "—"}</TableCell>
                  <TableCell>
                    <div className="flex flex-wrap gap-1">
                      {user.role_codes.length > 0
                        ? user.role_codes.map((code) => (
                            <Badge key={code} variant="outline">
                              {code}
                            </Badge>
                          ))
                        : <span className="text-muted-foreground text-xs">—</span>}
                    </div>
                  </TableCell>
                  <TableCell>
                    <div className="flex flex-wrap gap-1">
                      {!user.is_active ? (
                        <Badge variant="destructive">{t("admin.users.inactive")}</Badge>
                      ) : (
                        <Badge variant="secondary">{t("admin.users.active")}</Badge>
                      )}
                      {user.must_change_password ? (
                        <Badge variant="outline">{t("admin.users.mustChange")}</Badge>
                      ) : null}
                    </div>
                  </TableCell>
                  <TableCell>
                    <DropdownMenu>
                      <DropdownMenuTrigger asChild>
                        <Button variant="ghost" size="sm" aria-label={t("common.actions")}>
                          ⋯
                        </Button>
                      </DropdownMenuTrigger>
                      <DropdownMenuContent align="end">
                        {hasPerm("user:update") ? (
                          <DropdownMenuItem onClick={() => setEditing(user)}>
                            {t("common.edit")}
                          </DropdownMenuItem>
                        ) : null}
                        {hasPerm("user:reset_password") ? (
                          <DropdownMenuItem onClick={() => setResetting(user)}>
                            {t("admin.users.resetPassword")}
                          </DropdownMenuItem>
                        ) : null}
                        {hasPerm("user:force_logout") ? (
                          <DropdownMenuItem onClick={() => setEvicting(user)}>
                            {t("admin.users.forceLogout")}
                          </DropdownMenuItem>
                        ) : null}
                        {hasPerm("user:delete") ? (
                          <DropdownMenuItem variant="destructive" onClick={() => setDeleting(user)}>
                            {t("common.delete")}
                          </DropdownMenuItem>
                        ) : null}
                      </DropdownMenuContent>
                    </DropdownMenu>
                  </TableCell>
                </TableRow>
              ))
            ) : (
              <TableRow>
                <TableCell colSpan={7} className="text-muted-foreground">
                  {query ? t("common.notFound") : t("admin.users.empty")}
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>
      </div>

      {creating ? (
        <UserDialog
          roles={roles.data ?? []}
          mode="create"
          onClose={() => setCreating(false)}
          onSubmit={async (form) => {
            const input: UserCreateInput = {
              username: form.username,
              password: form.password,
              display_name: form.display_name,
              email: form.email || null,
              phone: form.phone || null,
              role_ids: form.role_ids,
            };
            await createUser(input);
            toast.success(t("admin.users.created", { username: form.username }));
            void invalidate();
          }}
        />
      ) : null}

      {editing ? (
        <UserDialog
          roles={roles.data ?? []}
          mode="edit"
          user={editing}
          onClose={() => setEditing(null)}
          onSubmit={async (form) => {
            const input: UserUpdateInput = {
              display_name: form.display_name,
              email: form.email || null,
              phone: form.phone || null,
              is_active: form.is_active,
              role_ids: form.role_ids,
            };
            await updateUser(editing.id, input);
            toast.success(t("admin.users.updated", { username: editing.username }));
            void invalidate();
          }}
        />
      ) : null}

      {resetting ? (
        <ResetPasswordDialog user={resetting} onClose={() => setResetting(null)} onDone={invalidate} />
      ) : null}

      <ConfirmDialog
        open={evicting !== null}
        onOpenChange={(open) => !open && setEvicting(null)}
        title={t("admin.users.forceLogout")}
        description={t("admin.users.forceLogoutConfirm", {
          username: evicting?.username ?? "",
        })}
        confirmLabel={t("admin.users.forceLogout")}
        pending={evict.isPending}
        onConfirm={() => evicting && evict.mutate(evicting.id)}
      />

      <ConfirmDialog
        open={deleting !== null}
        onOpenChange={(open) => !open && setDeleting(null)}
        title={t("admin.users.deleteTitle", { username: deleting?.username ?? "" })}
        description={t("admin.users.deleteConfirm")}
        confirmLabel={t("common.delete")}
        pending={remove.isPending}
        onConfirm={() => deleting && remove.mutate(deleting.id)}
      />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Create / edit dialog (shared shape, mode switch)
// ---------------------------------------------------------------------------

function UserDialog({
  roles,
  mode,
  user,
  onClose,
  onSubmit,
}: {
  roles: { id: number; code: string; name: string }[];
  mode: "create" | "edit";
  user?: CurrentUser;
  onClose: () => void;
  onSubmit: (form: UserFormState) => Promise<void>;
}) {
  const { t } = useTranslation();
  const [form, setForm] = useState<UserFormState>(
    mode === "edit" && user
      ? {
          username: user.username,
          password: "",
          display_name: user.display_name,
          email: user.email ?? "",
          phone: user.phone ?? "",
          is_active: user.is_active,
          role_ids: [],
        }
      : EMPTY_FORM,
  );
  const [pending, setPending] = useState(false);
  // Touched selection (ids); null = "user hasn't touched the picker yet", in
  // which case the checked set is DERIVED from the target's current role
  // codes — computed during render so a still-loading role list fills in
  // whenever it arrives, no effect needed.
  const [selectedRoles, setSelectedRoles] = useState<number[] | null>(mode === "edit" ? null : []);

  const effectiveRoleIds =
    selectedRoles ??
    (user ? roles.filter((r) => user.role_codes.includes(r.code)).map((r) => r.id) : []);

  function toggleRole(roleId: number, checked: boolean) {
    setSelectedRoles(
      checked ? [...effectiveRoleIds, roleId] : effectiveRoleIds.filter((id) => id !== roleId),
    );
  }

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    setPending(true);
    try {
      await onSubmit({ ...form, role_ids: effectiveRoleIds });
      onClose();
    } catch (error) {
      toast.error(apiErrorMessage(error));
    } finally {
      setPending(false);
    }
  }

  return (
    <Dialog open onOpenChange={(open) => !open && !pending && onClose()}>
      <DialogContent className="max-h-[85vh] overflow-y-auto sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>
            {mode === "create" ? t("admin.users.createTitle") : t("admin.users.editTitle", { username: form.username })}
          </DialogTitle>
        </DialogHeader>
        <form onSubmit={handleSubmit} className="grid gap-4">
          {mode === "create" ? (
            <>
              <div className="grid gap-2">
                <Label htmlFor="user-username">{t("admin.users.username")}</Label>
                <Input
                  id="user-username"
                  value={form.username}
                  onChange={(e) => setForm({ ...form, username: e.target.value })}
                  required
                  minLength={2}
                  pattern="[a-z0-9][a-z0-9._-]*"
                  autoFocus
                />
              </div>
              <div className="grid gap-2">
                <Label htmlFor="user-password">{t("admin.users.initialPassword")}</Label>
                <Input
                  id="user-password"
                  type="password"
                  value={form.password}
                  onChange={(e) => setForm({ ...form, password: e.target.value })}
                  required
                  minLength={8}
                />
                <p className="text-muted-foreground text-xs">{t("admin.users.initialPasswordHint")}</p>
              </div>
            </>
          ) : null}

          <div className="grid gap-2">
            <Label htmlFor="user-display">{t("admin.users.displayName")}</Label>
            <Input
              id="user-display"
              value={form.display_name}
              onChange={(e) => setForm({ ...form, display_name: e.target.value })}
            />
          </div>
          <div className="grid gap-2">
            <Label htmlFor="user-email">{t("admin.users.email")}</Label>
            <Input
              id="user-email"
              type="email"
              value={form.email}
              onChange={(e) => setForm({ ...form, email: e.target.value })}
            />
          </div>
          <div className="grid gap-2">
            <Label htmlFor="user-phone">{t("admin.users.phone")}</Label>
            <Input
              id="user-phone"
              type="tel"
              value={form.phone}
              onChange={(e) => setForm({ ...form, phone: e.target.value })}
              maxLength={32}
            />
            <p className="text-muted-foreground text-xs">{t("admin.users.phoneHint")}</p>
          </div>

          {mode === "edit" ? (
            <label className="flex items-center gap-2 rounded-lg border p-3 text-sm">
              <Checkbox
                checked={form.is_active}
                onCheckedChange={(checked) => setForm({ ...form, is_active: checked === true })}
              />
              <span>
                {t("admin.users.accountActive")}
                <span className="text-muted-foreground block text-xs">
                  {t("admin.users.accountActiveHint")}
                </span>
              </span>
            </label>
          ) : null}

          <div className="grid gap-2">
            <Label>{t("admin.users.roles")}</Label>
            <div className="grid gap-2 rounded-lg border p-3">
              {roles.length === 0 ? (
                <p className="text-muted-foreground text-xs">{t("common.loading")}</p>
              ) : (
                roles.map((role) => (
                  <label key={role.id} className="flex items-center gap-2 text-sm">
                    <Checkbox
                      checked={effectiveRoleIds.includes(role.id)}
                      onCheckedChange={(checked) => toggleRole(role.id, checked === true)}
                    />
                    <span className="font-mono text-xs">{role.code}</span>
                    <span className="text-muted-foreground">{role.name}</span>
                  </label>
                ))
              )}
            </div>
          </div>

          <DialogFooter>
            <Button type="button" variant="outline" onClick={onClose} disabled={pending}>
              {t("common.cancel")}
            </Button>
            <Button type="submit" disabled={pending}>
              {pending ? t("common.pending") : t("common.save")}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

// ---------------------------------------------------------------------------
// Reset password dialog
// ---------------------------------------------------------------------------

function ResetPasswordDialog({
  user,
  onClose,
  onDone,
}: {
  user: CurrentUser;
  onClose: () => void;
  onDone: () => void;
}) {
  const { t } = useTranslation();
  const [password, setPassword] = useState("");
  const [pending, setPending] = useState(false);

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    setPending(true);
    try {
      await resetPassword(user.id, password);
      toast.success(t("admin.users.passwordReset", { username: user.username }));
      onDone();
      onClose();
    } catch (error) {
      toast.error(apiErrorMessage(error));
    } finally {
      setPending(false);
    }
  }

  return (
    <Dialog open onOpenChange={(open) => !open && !pending && onClose()}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>{t("admin.users.resetFor", { username: user.username })}</DialogTitle>
        </DialogHeader>
        <form onSubmit={handleSubmit} className="grid gap-4">
          <div className="grid gap-2">
            <Label htmlFor="reset-password">{t("admin.users.newPassword")}</Label>
            <Input
              id="reset-password"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              minLength={8}
              autoFocus
            />
            <p className="text-muted-foreground text-xs">{t("admin.users.resetHint")}</p>
          </div>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={onClose} disabled={pending}>
              {t("common.cancel")}
            </Button>
            <Button type="submit" disabled={pending}>
              {pending ? t("common.pending") : t("common.save")}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
