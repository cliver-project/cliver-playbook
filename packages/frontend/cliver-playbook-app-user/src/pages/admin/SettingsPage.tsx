import { useState, type ReactNode } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";

import { useAuth } from "cliver-playbook-app-user/components/auth/AuthContext.tsx";
import { ConfirmDialog } from "cliver-playbook-app-basic/components/ConfirmDialog.tsx";
import { Badge } from "cliver-playbook-app-basic/components/ui/badge.tsx";
import { Button } from "cliver-playbook-app-basic/components/ui/button.tsx";
import { Checkbox } from "cliver-playbook-app-basic/components/ui/checkbox.tsx";
import { Input } from "cliver-playbook-app-basic/components/ui/input.tsx";
import { Label } from "cliver-playbook-app-basic/components/ui/label.tsx";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "cliver-playbook-app-basic/components/ui/select.tsx";
import { Textarea } from "cliver-playbook-app-basic/components/ui/textarea.tsx";
import { apiErrorMessage } from "cliver-playbook-app-basic/api/client.ts";
import {
  listSettings,
  resetSettings,
  updateSettings,
  type SettingsFieldInfo,
  type SettingsSectionInfo,
} from "cliver-playbook-app-user/api/auth.ts";

/**
 * Runtime settings, grouped by the package that owns them (ADR-0021).
 *
 * The page is schema-driven: each section arrives with its fields, allowed
 * values, and source. It never hard-codes a knob, so a package that registers
 * a new section appears here with no frontend change. Environment-managed
 * fields render read-only — the environment wins at the next restart. A
 * secret field renders a write-only password input: the stored value never
 * leaves the server, and an environment-managed secret is masked and locked.
 * Display gating only: the server rejects writes without `settings:manage`
 * regardless.
 *
 * Section copy is translated through `settingsSections.<key>` (mirroring the
 * field-name path, so `cliver_llm.model` nests as `cliver_llm.model`), with
 * the server's English string as the fallback. A package that registers a
 * section contributes only its own locale entries; an untranslated section
 * still renders. Fields sharing a `group` render together under one
 * translated heading, which keeps a large related configuration (the
 * cliver-core bindings) in one place; a `subgroup` nests a second heading
 * inside it. Both levels are collapsible blocks, so a large configuration
 * stays folded until the operator needs it.
 */
export default function SettingsPage() {
  const { t } = useTranslation();
  const { hasPerm } = useAuth();
  const sections = useQuery({ queryKey: ["settings"], queryFn: listSettings });
  const canManage = hasPerm("settings:manage");

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">{t("admin.settings.title")}</h1>
        <p className="text-muted-foreground text-sm">{t("admin.settings.description")}</p>
      </div>

      {sections.isLoading ? (
        <p className="text-muted-foreground text-sm">{t("common.loading")}</p>
      ) : sections.data && sections.data.length > 0 ? (
        sections.data.map((section) => (
          <SettingsSectionCard
            key={`${section.key}:${JSON.stringify(section.fields.map((f) => [f.value, f.source]))}`}
            section={section}
            canManage={canManage}
          />
        ))
      ) : (
        <p className="text-muted-foreground text-sm">{t("admin.settings.empty")}</p>
      )}
    </div>
  );
}

function SettingsSectionCard({
  section,
  canManage,
}: {
  section: SettingsSectionInfo;
  canManage: boolean;
}) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [draft, setDraft] = useState<Record<string, unknown>>(() =>
    draftFromFields(section.fields),
  );
  const [confirmReset, setConfirmReset] = useState(false);

  const sectionTitle = t(`settingsSections.${section.key}.title`, {
    defaultValue: section.title,
  });
  const sectionDescription = t(`settingsSections.${section.key}.description`, {
    defaultValue: section.description,
  });
  const { ungrouped, groups } = groupFields(section.fields);

  const renderField = (field: SettingsFieldInfo) => (
    <SettingsFieldInput
      key={field.name}
      sectionKey={section.key}
      field={field}
      value={field.read_only ? field.value : draft[field.name]}
      disabled={!canManage || field.read_only}
      onChange={(value) => setDraft((prev) => ({ ...prev, [field.name]: value }))}
    />
  );

  const save = useMutation({
    mutationFn: (values: Record<string, unknown>) => updateSettings(section.key, values),
    onSuccess: (updated) => {
      toast.success(
        t("admin.settings.saved", {
          title: t(`settingsSections.${updated.key}.title`, { defaultValue: updated.title }),
        }),
      );
      setDraft(draftFromFields(updated.fields));
      void queryClient.invalidateQueries({ queryKey: ["settings"] });
    },
    onError: (error) => toast.error(apiErrorMessage(error)),
  });

  const reset = useMutation({
    mutationFn: () => resetSettings(section.key),
    onSuccess: (updated) => {
      toast.success(
        t("admin.settings.resetDone", {
          title: t(`settingsSections.${updated.key}.title`, { defaultValue: updated.title }),
        }),
      );
      setDraft(draftFromFields(updated.fields));
      setConfirmReset(false);
      void queryClient.invalidateQueries({ queryKey: ["settings"] });
    },
    onError: (error) => toast.error(apiErrorMessage(error)),
  });

  function handleSave() {
    const result = payloadFromDraft(section, draft, (field) =>
      t(`settingsSections.${section.key}.fields.${field.name}.label`, {
        defaultValue: field.label,
      }),
    );
    if ("error" in result) {
      toast.error(
        t(
          result.error === "json"
            ? "admin.settings.invalidJson"
            : "admin.settings.invalidNumber",
          { field: result.field },
        ),
      );
      return;
    }
    save.mutate(result.values);
  }

  return (
    <section className="space-y-4 rounded-lg border p-4">
      <div className="flex items-start gap-3">
        <div className="flex-1 space-y-1">
          <h2 className="text-lg font-medium">{sectionTitle}</h2>
          <p className="text-muted-foreground text-sm">{sectionDescription}</p>
        </div>
        <Badge variant="outline" className="font-mono text-xs">
          {section.key}
        </Badge>
      </div>

      {ungrouped.length > 0 ? (
        <div className="grid gap-4 md:grid-cols-2">{ungrouped.map(renderField)}</div>
      ) : null}

      {groups.map((group) => (
        <CollapsibleBlock
          key={group.key}
          defaultOpen
          title={t(`settingsSections.${section.key}.groups.${group.key}.title`, {
            defaultValue: group.title,
          })}
        >
          {group.fields.length > 0 ? (
            <div className="grid gap-4 md:grid-cols-2">{group.fields.map(renderField)}</div>
          ) : null}
          {group.subgroups.map((subgroup) => (
            <CollapsibleBlock
              key={subgroup.key}
              title={t(
                `settingsSections.${section.key}.groups.${group.key}.subgroups.${subgroup.key}.title`,
                { defaultValue: subgroup.title },
              )}
            >
              <div className="grid gap-4 md:grid-cols-2">
                {subgroup.fields.map(renderField)}
              </div>
            </CollapsibleBlock>
          ))}
        </CollapsibleBlock>
      ))}

      {canManage ? (
        <div className="flex items-center justify-end gap-2">
          <Button
            variant="outline"
            onClick={() => setConfirmReset(true)}
            disabled={save.isPending || reset.isPending}
          >
            {t("admin.settings.reset")}
          </Button>
          <Button onClick={handleSave} disabled={save.isPending || reset.isPending}>
            {save.isPending ? t("common.pending") : t("common.save")}
          </Button>
        </div>
      ) : null}

      <ConfirmDialog
        open={confirmReset}
        onOpenChange={(open) => !open && setConfirmReset(false)}
        title={t("admin.settings.resetTitle", { title: sectionTitle })}
        description={t("admin.settings.resetConfirm")}
        confirmLabel={t("admin.settings.reset")}
        pending={reset.isPending}
        onConfirm={() => reset.mutate()}
      />
    </section>
  );
}

function SettingsFieldInput({
  sectionKey,
  field,
  value,
  disabled,
  onChange,
}: {
  sectionKey: string;
  field: SettingsFieldInfo;
  value: unknown;
  disabled: boolean;
  onChange: (value: unknown) => void;
}) {
  const { t } = useTranslation();
  const inputId = `setting-${field.name.replaceAll(".", "-")}`;
  const label = t(`settingsSections.${sectionKey}.fields.${field.name}.label`, {
    defaultValue: field.label,
  });
  const description = t(`settingsSections.${sectionKey}.fields.${field.name}.description`, {
    defaultValue: field.description,
  });

  if (field.secret) {
    // A stored secret is never sent back. When the environment manages the
    // field the input is masked and read-only; otherwise the operator may
    // type a replacement, which is persisted with the section.
    return (
      <div className="grid gap-2">
        <div className="flex flex-wrap items-center gap-2">
          <Label htmlFor={inputId}>{label}</Label>
          <Badge variant="outline" className="text-xs">
            {field.configured
              ? t("admin.settings.secretConfigured")
              : t("admin.settings.secretMissing")}
          </Badge>
        </div>
        {field.read_only ? (
          <Input
            id={inputId}
            value={field.configured ? "••••••••" : ""}
            placeholder={
              field.env_var ? t("admin.settings.secretHint", { env: field.env_var }) : ""
            }
            disabled
            readOnly
          />
        ) : (
          <Input
            id={inputId}
            type="password"
            autoComplete="new-password"
            value={typeof value === "string" ? value : ""}
            placeholder={
              field.configured
                ? t("admin.settings.secretReplaceHint")
                : t("admin.settings.secretEnterHint")
            }
            onChange={(event) => onChange(event.target.value)}
            disabled={disabled}
          />
        )}
        <FieldHint field={field} description={description} />
      </div>
    );
  }

  return (
    <div className="grid gap-2">
      <div className="flex flex-wrap items-center gap-2">
        <Label htmlFor={inputId}>{label}</Label>
        <Badge variant={field.source === "runtime" ? "default" : "outline"} className="text-xs">
          {t(`admin.settings.sources.${field.source}`)}
        </Badge>
      </div>

      {field.type === "boolean" ? (
        <div className="flex h-9 items-center gap-2">
          <Checkbox
            id={inputId}
            checked={value === true}
            onCheckedChange={(checked) => onChange(checked === true)}
            disabled={disabled}
          />
          <span className="text-muted-foreground text-sm">{description}</span>
        </div>
      ) : field.type === "enum" ? (
        <Select
          value={typeof value === "string" ? value : ""}
          onValueChange={onChange}
          disabled={disabled}
        >
          <SelectTrigger id={inputId} className="w-full">
            <SelectValue placeholder={t("admin.settings.selectValue")} />
          </SelectTrigger>
          <SelectContent>
            {(field.enum ?? []).map((choice) => (
              <SelectItem key={choice} value={choice}>
                {choice}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      ) : field.type === "json" ? (
        <Textarea
          id={inputId}
          className="min-h-24 font-mono text-xs"
          value={typeof value === "string" ? value : JSON.stringify(value ?? {}, null, 2)}
          onChange={(event) => onChange(event.target.value)}
          disabled={disabled}
          spellCheck={false}
        />
      ) : (
        <Input
          id={inputId}
          type={field.type === "integer" || field.type === "number" ? "number" : "text"}
          step={field.type === "integer" ? 1 : field.type === "number" ? "any" : undefined}
          min={field.minimum ?? undefined}
          max={field.maximum ?? undefined}
          value={typeof value === "number" || typeof value === "string" ? value : ""}
          onChange={(event) => onChange(event.target.value)}
          disabled={disabled}
        />
      )}

      <FieldHint field={field} description={description} />
    </div>
  );
}

function FieldHint({ field, description }: { field: SettingsFieldInfo; description: string }) {
  return (
    <div className="space-y-1">
      {description ? <p className="text-muted-foreground text-xs">{description}</p> : null}
      {field.env_var ? (
        <p className="text-muted-foreground font-mono text-xs">
          {field.env_var}
          {field.minimum !== null || field.maximum !== null
            ? ` · ${rangeLabel(field)}`
            : ""}
        </p>
      ) : field.minimum !== null || field.maximum !== null ? (
        <p className="text-muted-foreground text-xs">{rangeLabel(field)}</p>
      ) : null}
    </div>
  );
}

function rangeLabel(field: SettingsFieldInfo): string {
  if (field.minimum !== null && field.maximum !== null) {
    return `${field.minimum}–${field.maximum}`;
  }
  return field.minimum !== null ? `≥ ${field.minimum}` : `≤ ${field.maximum}`;
}

type FieldSubgroup = { key: string; title: string; fields: SettingsFieldInfo[] };

type FieldGroup = {
  key: string;
  title: string;
  fields: SettingsFieldInfo[];
  subgroups: FieldSubgroup[];
};

/**
 * Split fields into the ungrouped block and ordered groups.
 *
 * Group and subgroup order follows first appearance, so the owning package
 * controls it by field order. A field's subgroup nests inside its group;
 * fields without a group render first, in their original order.
 */
function groupFields(fields: SettingsFieldInfo[]): {
  ungrouped: SettingsFieldInfo[];
  groups: FieldGroup[];
} {
  const ungrouped: SettingsFieldInfo[] = [];
  const groups = new Map<string, FieldGroup>();
  for (const field of fields) {
    if (!field.group) {
      ungrouped.push(field);
      continue;
    }
    let group = groups.get(field.group);
    if (!group) {
      group = {
        key: field.group,
        title: field.group_title,
        fields: [],
        subgroups: [],
      };
      groups.set(field.group, group);
    }
    if (!field.subgroup) {
      group.fields.push(field);
      continue;
    }
    let subgroup = group.subgroups.find((entry) => entry.key === field.subgroup);
    if (!subgroup) {
      subgroup = { key: field.subgroup, title: field.subgroup_title, fields: [] };
      group.subgroups.push(subgroup);
    }
    subgroup.fields.push(field);
  }
  return { ungrouped, groups: [...groups.values()] };
}

/**
 * A native `<details>` block, open state mirrored in React.
 *
 * Mirroring matters: an uncontrolled `open` attribute would be reapplied on
 * every render (for example while typing into a field), snapping a block the
 * operator just collapsed back open. Nesting works without Tailwind group
 * variants, which would otherwise match an outer open block.
 */
function CollapsibleBlock({
  title,
  defaultOpen = false,
  children,
}: {
  title: string;
  defaultOpen?: boolean;
  children: ReactNode;
}) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <details
      open={open}
      onToggle={(event) => setOpen(event.currentTarget.open)}
      className="rounded-md border bg-muted/20"
    >
      <summary className="flex cursor-pointer list-none items-center gap-2 px-3 py-2 text-sm font-medium select-none [&::-webkit-details-marker]:hidden">
        <svg
          aria-hidden="true"
          viewBox="0 0 16 16"
          fill="none"
          className={`size-4 shrink-0 transition-transform ${open ? "rotate-90" : ""}`}
        >
          <path
            d="M6 4l4 4-4 4"
            stroke="currentColor"
            strokeWidth="1.5"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </svg>
        <span>{title}</span>
      </summary>
      <div className="space-y-3 px-3 pb-3">{children}</div>
    </details>
  );
}

/**
 * Editable starting state. Env-managed fields are skipped entirely. A secret
 * starts empty because the server never returns it, so an untouched key is
 * not resent and cannot overwrite the stored value with a blank.
 */
function draftFromFields(fields: SettingsFieldInfo[]): Record<string, unknown> {
  const draft: Record<string, unknown> = {};
  for (const field of fields) {
    if (field.read_only) continue;
    if (field.type === "json") {
      draft[field.name] = JSON.stringify(field.value ?? {}, null, 2);
    } else if (field.value !== null && field.value !== undefined) {
      draft[field.name] = field.value;
    } else {
      draft[field.name] =
        field.type === "boolean" ? false : field.type === "string" ? "" : 0;
    }
  }
  return draft;
}

type DraftResult =
  | { values: Record<string, unknown> }
  | { error: "json" | "number"; field: string };

/**
 * Convert form strings to the types the API expects.
 *
 * Only fields whose draft differs from the loaded value are sent. A save is a
 * partial update: including untouched fields would persist them as runtime
 * overrides and silently pin them against later `app.yaml` changes.
 */
function payloadFromDraft(
  section: SettingsSectionInfo,
  draft: Record<string, unknown>,
  labelFor: (field: SettingsFieldInfo) => string,
): DraftResult {
  const loaded = draftFromFields(section.fields);
  const values: Record<string, unknown> = {};
  for (const field of section.fields) {
    if (field.read_only) continue;
    const raw = draft[field.name];
    if (raw === loaded[field.name]) continue;
    if (field.type === "json") {
      try {
        values[field.name] = raw === "" || raw === undefined ? {} : JSON.parse(String(raw));
      } catch {
        return { error: "json", field: labelFor(field) };
      }
    } else if (field.type === "integer" || field.type === "number") {
      const parsed = typeof raw === "number" ? raw : Number(raw);
      if (!Number.isFinite(parsed)) {
        return { error: "number", field: labelFor(field) };
      }
      values[field.name] = field.type === "integer" ? Math.trunc(parsed) : parsed;
    } else if (field.type === "boolean") {
      values[field.name] = raw === true;
    } else {
      values[field.name] = raw ?? "";
    }
  }
  return { values };
}
