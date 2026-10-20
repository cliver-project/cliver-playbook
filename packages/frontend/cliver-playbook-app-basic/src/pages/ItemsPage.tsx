import { useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { Pencil, Plus, Trash2 } from "lucide-react";

import {
  createItem,
  deleteItem,
  listItems,
  updateItem,
  type Item,
  type ItemCreateInput,
  type ItemUpdateInput,
} from "cliver-playbook-app-basic/api/items.ts";
import { ConfirmDialog } from "cliver-playbook-app-basic/components/ConfirmDialog.tsx";
import { DataTable, type DataTableColumn } from "cliver-playbook-app-basic/crud/DataTable.tsx";
import { useCrudQueries } from "cliver-playbook-app-basic/crud/useCrudQueries.ts";
import { Button } from "cliver-playbook-app-basic/components/ui/button.tsx";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "cliver-playbook-app-basic/components/ui/dialog.tsx";
import { Input } from "cliver-playbook-app-basic/components/ui/input.tsx";
import { Label } from "cliver-playbook-app-basic/components/ui/label.tsx";

/**
 * Reference entity-CRUD page — copy this file for a new entity and swap:
 * the api module, the form fields, the columns, and the i18n keys. Everything
 * else (list query, mutations, invalidation, toasts, table states, dialog
 * open/pending flow) comes from the shared crud/ components.
 */

/** Create/edit form state — one object keeps the dialog wiring trivial. */
interface ItemForm {
  name: string;
  description: string;
  quantity: string; // kept as string in inputs; parsed on submit
}

const EMPTY_FORM: ItemForm = { name: "", description: "", quantity: "0" };

function toForm(item: Item): ItemForm {
  return { name: item.name, description: item.description, quantity: String(item.quantity) };
}

export default function ItemsPage() {
  const { t } = useTranslation();

  const [creating, setCreating] = useState(false);
  const [editing, setEditing] = useState<Item | null>(null);
  const [deleting, setDeleting] = useState<Item | null>(null);

  const crud = useCrudQueries<Item, ItemCreateInput, ItemUpdateInput>({
    queryKey: ["items"],
    list: listItems,
    create: createItem,
    update: updateItem,
    remove: deleteItem,
    messages: {
      created: t("items.created"),
      updated: t("items.updated"),
      deleted: t("items.deleted"),
    },
    // Any successful mutation closes whichever dialog is open. Setting all
    // three is idempotent — only one can be non-null at a time.
    onSuccess: () => {
      setCreating(false);
      setEditing(null);
      setDeleting(null);
    },
  });

  const columns: DataTableColumn<Item>[] = [
    { key: "name", header: t("items.name"), render: (item) => <span className="font-medium">{item.name}</span> },
    { key: "quantity", header: t("items.quantity"), render: (item) => item.quantity, className: "w-24" },
    {
      key: "description",
      header: t("items.description"),
      render: (item) => (
        <span className="text-muted-foreground line-clamp-1 max-w-96">{item.description || "—"}</span>
      ),
    },
    {
      key: "updated",
      header: t("items.updatedAt"),
      render: (item) => (
        <span className="text-muted-foreground whitespace-nowrap text-xs">
          {new Date(item.updated_at).toLocaleString()}
        </span>
      ),
    },
    {
      key: "actions",
      header: <span className="sr-only">{t("common.actions")}</span>,
      render: (item) => (
        <div className="flex justify-end gap-1">
          <Button variant="ghost" size="sm" onClick={() => setEditing(item)} aria-label={t("common.edit")}>
            <Pencil className="size-4" />
          </Button>
          <Button
            variant="ghost"
            size="sm"
            className="text-destructive"
            onClick={() => setDeleting(item)}
            aria-label={t("common.delete")}
          >
            <Trash2 className="size-4" />
          </Button>
        </div>
      ),
      className: "w-24",
    },
  ];

  async function handleSubmit(form: ItemForm, id?: number) {
    const quantity = Number(form.quantity || 0);
    if (id !== undefined) {
      await crud.update.mutateAsync({ id, input: { ...form, quantity } });
    } else {
      await crud.create.mutateAsync({ ...form, quantity });
    }
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3">
        <h1 className="text-2xl font-semibold tracking-tight">{t("items.title")}</h1>
        <Button className="ml-auto" onClick={() => setCreating(true)}>
          <Plus className="size-4" />
          {t("items.create")}
        </Button>
      </div>

      <DataTable
        columns={columns}
        rows={crud.items.data}
        rowKey={(item) => item.id}
        isLoading={crud.items.isLoading}
        emptyLabel={t("items.empty")}
      />

      {creating ? (
        <ItemDialog
          title={t("items.createTitle")}
          initial={EMPTY_FORM}
          pending={crud.create.isPending}
          onClose={() => setCreating(false)}
          onSubmit={(form) => handleSubmit(form)}
        />
      ) : null}

      {editing ? (
        <ItemDialog
          title={t("items.editTitle", { name: editing.name })}
          initial={toForm(editing)}
          pending={crud.update.isPending}
          onClose={() => setEditing(null)}
          onSubmit={(form) => handleSubmit(form, editing.id)}
        />
      ) : null}

      <ConfirmDialog
        open={deleting !== null}
        onOpenChange={(open) => !open && setDeleting(null)}
        title={t("items.deleteTitle", { name: deleting?.name ?? "" })}
        description={t("items.deleteConfirm")}
        confirmLabel={t("common.delete")}
        pending={crud.remove.isPending}
        onConfirm={() => deleting && crud.remove.mutate(deleting.id)}
      />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Create / edit dialog (shared shape, prefilled from the row when editing)
// ---------------------------------------------------------------------------

function ItemDialog({
  title,
  initial,
  pending,
  onClose,
  onSubmit,
}: {
  title: string;
  initial: ItemForm;
  pending: boolean;
  onClose: () => void;
  onSubmit: (form: ItemForm) => Promise<void>;
}) {
  const { t } = useTranslation();
  const [form, setForm] = useState<ItemForm>(initial);

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    await onSubmit(form);
    onClose();
  }

  return (
    <Dialog open onOpenChange={(open) => !open && !pending && onClose()}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
        </DialogHeader>
        <form onSubmit={handleSubmit} className="grid gap-4">
          <div className="grid gap-2">
            <Label htmlFor="item-name">{t("items.name")}</Label>
            <Input
              id="item-name"
              value={form.name}
              onChange={(e) => setForm({ ...form, name: e.target.value })}
              required
              maxLength={200}
              autoFocus
            />
          </div>
          <div className="grid gap-2">
            <Label htmlFor="item-quantity">{t("items.quantity")}</Label>
            <Input
              id="item-quantity"
              type="number"
              min={0}
              value={form.quantity}
              onChange={(e) => setForm({ ...form, quantity: e.target.value })}
              required
            />
          </div>
          <div className="grid gap-2">
            <Label htmlFor="item-description">{t("items.description")}</Label>
            <Input
              id="item-description"
              value={form.description}
              onChange={(e) => setForm({ ...form, description: e.target.value })}
            />
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
