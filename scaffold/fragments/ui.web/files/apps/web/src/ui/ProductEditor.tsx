import { useTranslation } from "react-i18next";

import { Button } from "cliver-playbook-app-basic/components/ui/button.tsx";
import { Input } from "cliver-playbook-app-basic/components/ui/input.tsx";
import { Textarea } from "cliver-playbook-app-basic/components/ui/textarea.tsx";

export type ProductForm = {
  name: string;
  description: string;
  price_cents: number;
};

export function ProductEditor({
  isEdit,
  form,
  onChange,
  onSave,
  onCancel,
  busy,
  error,
}: {
  isEdit: boolean;
  form: ProductForm;
  onChange: (form: ProductForm) => void;
  onSave: () => void;
  onCancel: () => void;
  busy: boolean;
  error?: string | null;
}) {
  const { t } = useTranslation();
  return (
    <form
      className="flex flex-col gap-4"
      onSubmit={(event) => {
        event.preventDefault();
        onSave();
      }}
    >
      <h1 className="text-2xl font-semibold">
        {isEdit ? t("products.edit") : t("products.create")}
      </h1>
      <label className="flex flex-col gap-1 text-sm">
        <span>{t("products.name")}</span>
        <Input
          value={form.name}
          onChange={(event) => onChange({ ...form, name: event.target.value })}
        />
      </label>
      <label className="flex flex-col gap-1 text-sm">
        <span>{t("products.description")}</span>
        <Textarea
          className="min-h-32"
          value={form.description}
          onChange={(event) =>
            onChange({ ...form, description: event.target.value })
          }
        />
      </label>
      <label className="flex flex-col gap-1 text-sm">
        <span>{t("products.price")}</span>
        <Input
          min={0}
          type="number"
          value={form.price_cents}
          onChange={(event) =>
            onChange({ ...form, price_cents: Number(event.target.value) })
          }
        />
      </label>
      {error ? <p className="text-sm text-destructive">{error}</p> : null}
      <div className="flex gap-2">
        <Button type="submit" disabled={busy}>
          {t("products.save")}
        </Button>
        <Button type="button" variant="outline" onClick={onCancel}>
          {t("products.cancel")}
        </Button>
      </div>
    </form>
  );
}
