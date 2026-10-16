import { useMemo, useState, type FormEvent } from "react";
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
import { Input } from "cliver-playbook-app-basic/components/ui/input.tsx";
import { Label } from "cliver-playbook-app-basic/components/ui/label.tsx";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "cliver-playbook-app-basic/components/ui/table.tsx";
import { apiErrorMessage } from "cliver-playbook-app-basic/api/client.ts";
import {
  createRole,
  deleteRole,
  listPermissions,
  listRoles,
  updateRole,
  type Role,
  type RoleInput,
  type RoleUpdateInput,
} from "cliver-playbook-app-user/api/auth.ts";

/**
 * Role administration: roles are permission bundles (ADR-0003 — the catalog
 * lives in code, roles are data). The editor renders the catalog grouped by
 * its `group` field; anything outside the catalog cannot be granted because
 * the server rejects unknown codes with a 400.
 *
 * System roles (admin, user — seeded by the migration) are immutable in the
 * ways that matter: they cannot be deleted and their code cannot change.
 */

interface RoleFormState {
  code: string;
  name: string;
  description: string;
  permission_codes: string[];
}

const EMPTY_FORM: RoleFormState = { code: "", name: "", description: "", permission_codes: [] };

export default function RolesPage() {
  const { t } = useTranslation();
  const { hasPerm } = useAuth();
  const queryClient = useQueryClient();

  const roles = useQuery({ queryKey: ["roles"], queryFn: listRoles });
  const catalog = useQuery({ queryKey: ["permissions"], queryFn: listPermissions, staleTime: 5 * 60_000 });

  const [creating, setCreating] = useState(false);
  const [editing, setEditing] = useState<Role | null>(null);
  const [deleting, setDeleting] = useState<Role | null>(null);

  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: ["roles"] });
  };

  const remove = useMutation({
    mutationFn: (id: number) => deleteRole(id),
    onSuccess: () => {
      toast.success(t("admin.roles.deleted"));
      setDeleting(null);
      invalidate();
    },
    onError: (error) => toast.error(apiErrorMessage(error)),
  });

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3">
        <h1 className="text-2xl font-semibold tracking-tight">{t("admin.roles.title")}</h1>
        {hasPerm("role:manage") ? (
          <Button className="ml-auto" onClick={() => setCreating(true)}>
            {t("admin.roles.create")}
          </Button>
        ) : null}
      </div>

      <div className="rounded-lg border">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>{t("admin.roles.code")}</TableHead>
              <TableHead>{t("admin.roles.name")}</TableHead>
              <TableHead>{t("admin.roles.description")}</TableHead>
              <TableHead>{t("admin.roles.permissions")}</TableHead>
              <TableHead className="w-24" />
            </TableRow>
          </TableHeader>
          <TableBody>
            {roles.isLoading ? (
              <TableRow>
                <TableCell colSpan={5} className="text-muted-foreground">
                  {t("common.loading")}
                </TableCell>
              </TableRow>
            ) : roles.data && roles.data.length > 0 ? (
              roles.data.map((role) => (
                <TableRow key={role.id}>
                  <TableCell className="font-mono text-sm font-medium">{role.code}</TableCell>
                  <TableCell>{role.name}</TableCell>
                  <TableCell className="text-muted-foreground max-w-64 truncate">
                    {role.description || "—"}
                  </TableCell>
                  <TableCell>
                    {role.permission_codes.length > 0 ? (
                      <div className="flex max-w-72 flex-wrap gap-1">
                        {role.permission_codes.map((code) => (
                          <Badge key={code} variant="outline" className="font-mono text-xs">
                            {code}
                          </Badge>
                        ))}
                      </div>
                    ) : (
                      <span className="text-muted-foreground text-xs">—</span>
                    )}
                  </TableCell>
                  <TableCell>
                    {hasPerm("role:manage") ? (
                      <div className="flex items-center gap-1">
                        <Button variant="ghost" size="sm" onClick={() => setEditing(role)}>
                          {t("common.edit")}
                        </Button>
                        {!role.is_system ? (
                          <Button
                            variant="ghost"
                            size="sm"
                            className="text-destructive"
                            onClick={() => setDeleting(role)}
                          >
                            {t("common.delete")}
                          </Button>
                        ) : null}
                      </div>
                    ) : null}
                  </TableCell>
                </TableRow>
              ))
            ) : (
              <TableRow>
                <TableCell colSpan={5} className="text-muted-foreground">
                  {t("admin.roles.empty")}
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>
      </div>

      {creating ? (
        <RoleDialog
          catalog={catalog.data ?? []}
          onClose={() => setCreating(false)}
          onSubmit={async (form) => {
            const input: RoleInput = { ...form };
            await createRole(input);
            toast.success(t("admin.roles.created", { code: form.code }));
            invalidate();
          }}
        />
      ) : null}

      {editing ? (
        <RoleDialog
          catalog={catalog.data ?? []}
          role={editing}
          onClose={() => setEditing(null)}
          onSubmit={async (form) => {
            const input: RoleUpdateInput = {
              name: form.name,
              description: form.description,
              permission_codes: form.permission_codes,
            };
            await updateRole(editing.id, input);
            toast.success(t("admin.roles.updated", { code: editing.code }));
            invalidate();
          }}
        />
      ) : null}

      <ConfirmDialog
        open={deleting !== null}
        onOpenChange={(open) => !open && setDeleting(null)}
        title={t("admin.roles.deleteTitle", { code: deleting?.code ?? "" })}
        description={t("admin.roles.deleteConfirm")}
        confirmLabel={t("common.delete")}
        pending={remove.isPending}
        onConfirm={() => deleting && remove.mutate(deleting.id)}
      />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Create / edit dialog
// ---------------------------------------------------------------------------

function RoleDialog({
  catalog,
  role,
  onClose,
  onSubmit,
}: {
  catalog: { code: string; name: string; group: string }[];
  role?: Role;
  onClose: () => void;
  onSubmit: (form: RoleFormState) => Promise<void>;
}) {
  const { t } = useTranslation();
  const [form, setForm] = useState<RoleFormState>(
    role
      ? {
          code: role.code,
          name: role.name,
          description: role.description,
          permission_codes: [...role.permission_codes],
        }
      : EMPTY_FORM,
  );
  const [pending, setPending] = useState(false);

  /** Catalog grouped by its `group` field, insertion order preserved. */
  const grouped = useMemo(() => {
    const map = new Map<string, { code: string; name: string }[]>();
    for (const item of catalog) {
      const bucket = map.get(item.group) ?? [];
      bucket.push(item);
      map.set(item.group, bucket);
    }
    return [...map.entries()];
  }, [catalog]);

  function togglePermission(code: string, checked: boolean) {
    setForm((prev) => ({
      ...prev,
      permission_codes: checked
        ? [...prev.permission_codes, code]
        : prev.permission_codes.filter((c) => c !== code),
    }));
  }

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    setPending(true);
    try {
      await onSubmit(form);
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
            {role ? t("admin.roles.editTitle", { code: role.code }) : t("admin.roles.createTitle")}
          </DialogTitle>
        </DialogHeader>
        <form onSubmit={handleSubmit} className="grid gap-4">
          <div className="grid gap-2">
            <Label htmlFor="role-code">{t("admin.roles.code")}</Label>
            <Input
              id="role-code"
              value={form.code}
              onChange={(e) => setForm({ ...form, code: e.target.value })}
              // The code is the role's stable identity: editable only at
              // creation (the server refuses code changes on system roles).
              disabled={Boolean(role)}
              required
              minLength={2}
              pattern="[a-z0-9][a-z0-9._-]*"
              autoFocus={!role}
            />
          </div>
          <div className="grid gap-2">
            <Label htmlFor="role-name">{t("admin.roles.name")}</Label>
            <Input
              id="role-name"
              value={form.name}
              onChange={(e) => setForm({ ...form, name: e.target.value })}
              required
              autoFocus={Boolean(role)}
            />
          </div>
          <div className="grid gap-2">
            <Label htmlFor="role-desc">{t("admin.roles.description")}</Label>
            <Input
              id="role-desc"
              value={form.description}
              onChange={(e) => setForm({ ...form, description: e.target.value })}
            />
          </div>

          <div className="grid gap-2">
            <Label>{t("admin.roles.permissions")}</Label>
            <div className="grid gap-4 rounded-lg border p-3">
              {grouped.length === 0 ? (
                <p className="text-muted-foreground text-xs">{t("common.loading")}</p>
              ) : (
                grouped.map(([group, items]) => (
                  <div key={group} className="space-y-2">
                    <p className="text-muted-foreground text-xs font-medium uppercase tracking-wide">
                      {group}
                    </p>
                    {items.map((item) => (
                      <label key={item.code} className="flex items-center gap-2 text-sm">
                        <Checkbox
                          checked={form.permission_codes.includes(item.code)}
                          onCheckedChange={(checked) =>
                            togglePermission(item.code, checked === true)
                          }
                        />
                        <span className="font-mono text-xs">{item.code}</span>
                        <span className="text-muted-foreground">{item.name}</span>
                      </label>
                    ))}
                  </div>
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
