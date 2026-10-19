import { useTranslation } from "react-i18next";

import type { StageOptionField } from "cliver-playbook-app-rag/api/rag.ts";
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

/**
 * Renders a chunker's output-shaping options from the server catalog.
 *
 * The server describes each option as a flat primitive (`boolean`,
 * `integer`, `string`, `enum`), so this component maps one descriptor to
 * one control and never knows which chunker it is rendering. Adding a new
 * chunker option on the backend therefore needs no frontend change.
 *
 * Drafts are kept as strings (or booleans) rather than parsed values:
 * an input the user is still typing must not be coerced into a number on
 * every keystroke, and an empty string is a meaningful "use the default"
 * state for nullable options.
 */

export type OptionDraft = string | boolean;
export type OptionDrafts = Record<string, OptionDraft>;

/** One draft per field, initialized from the server's defaults. */
export function initialOptionDrafts(fields: StageOptionField[]): OptionDrafts {
  const drafts: OptionDrafts = {};
  for (const field of fields) {
    if (field.type === "boolean") {
      drafts[field.name] = field.default === true;
    } else {
      drafts[field.name] = field.default === null ? "" : String(field.default);
    }
  }
  return drafts;
}

/** Convert drafts into the JSON object sent as `chunker_options`. */
export function buildChunkerOptions(
  fields: StageOptionField[],
  drafts: OptionDrafts,
): Record<string, unknown> {
  const options: Record<string, unknown> = {};
  for (const field of fields) {
    const draft = drafts[field.name];
    if (field.type === "boolean") {
      options[field.name] = draft === true;
      continue;
    }

    const raw = typeof draft === "string" ? draft.trim() : "";
    if (field.type === "integer") {
      if (raw === "") continue;
      const value = Number(raw);
      // Invalid values are blocked by `chunkerOptionsInvalid`; omitting
      // them here keeps a malformed draft from silently becoming NaN.
      if (Number.isInteger(value)) options[field.name] = value;
      continue;
    }

    // An empty nullable string means "no value", which is different from
    // an empty string value; the server default stays in force.
    if (raw === "" && field.default === null) continue;
    if (raw !== "") options[field.name] = raw;
  }
  return options;
}

/**
 * Names of drafts that cannot be uploaded.
 *
 * Only the shapes the server's option descriptors can express are
 * validated: integer bounds, enum membership, and required strings.
 * Boolean controls cannot be invalid.
 */
export function chunkerOptionsInvalid(
  fields: StageOptionField[],
  drafts: OptionDrafts,
): string[] {
  const invalid: string[] = [];
  for (const field of fields) {
    const draft = drafts[field.name];
    if (field.type === "boolean") continue;

    const raw = typeof draft === "string" ? draft.trim() : "";
    if (field.type === "integer") {
      if (raw === "") {
        if (field.default === null) continue;
        invalid.push(field.name);
        continue;
      }
      const value = Number(raw);
      const belowMinimum = field.minimum !== null && value < field.minimum;
      const aboveMaximum = field.maximum !== null && value > field.maximum;
      if (!Number.isInteger(value) || belowMinimum || aboveMaximum) {
        invalid.push(field.name);
      }
      continue;
    }

    if (field.type === "enum") {
      if (!(field.enum ?? []).includes(raw)) invalid.push(field.name);
      continue;
    }

    if (raw === "" && field.default !== null) invalid.push(field.name);
  }
  return invalid;
}

/** Convert snake_case option names into the i18n key segment. */
function translationKey(name: string): string {
  return name.replace(/_([a-z])/g, (_, letter: string) => letter.toUpperCase());
}

export interface ChunkerOptionsFormProps {
  fields: StageOptionField[];
  drafts: OptionDrafts;
  onChange: (name: string, value: OptionDraft) => void;
  disabled?: boolean;
  /** Field names reported by `chunkerOptionsInvalid`. */
  invalid?: readonly string[];
}

export function ChunkerOptionsForm({
  fields,
  drafts,
  onChange,
  disabled = false,
  invalid = [],
}: ChunkerOptionsFormProps) {
  const { t } = useTranslation();
  if (fields.length === 0) return null;

  const invalidNames = new Set(invalid);

  return (
    <div className="space-y-3">
      <div>
        <p className="text-sm font-medium">{t("rag.chunkers.title")}</p>
        <p className="text-muted-foreground text-xs">{t("rag.chunkers.hint")}</p>
      </div>
      <div className="grid gap-4 md:grid-cols-2">
        {fields.map((field) => {
          const key = translationKey(field.name);
          const inputId = `rag-chunker-option-${field.name}`;
          const draft = drafts[field.name];
          const label = t(`rag.chunkers.options.${key}`, {
            defaultValue: field.label,
          });
          const hint = t(`rag.chunkers.options.${key}Description`, {
            defaultValue: field.description,
          });
          const isInvalid = invalidNames.has(field.name);

          return (
            <div className="space-y-1.5" key={field.name}>
              {field.type === "boolean" ? (
                <div className="flex items-center gap-2">
                  <Checkbox
                    id={inputId}
                    checked={draft === true}
                    onCheckedChange={(checked) => onChange(field.name, checked === true)}
                    disabled={disabled}
                  />
                  <Label htmlFor={inputId}>{label}</Label>
                </div>
              ) : (
                <>
                  <Label htmlFor={inputId}>{label}</Label>
                  {field.type === "enum" ? (
                    <Select
                      value={typeof draft === "string" ? draft : ""}
                      onValueChange={(value) => onChange(field.name, value)}
                      disabled={disabled}
                    >
                      <SelectTrigger id={inputId} className="w-full">
                        <SelectValue placeholder={t("rag.common.selectStage")} />
                      </SelectTrigger>
                      <SelectContent>
                        {(field.enum ?? []).map((value) => (
                          <SelectItem key={value} value={value}>
                            {t(`rag.chunkers.values.${value}`, { defaultValue: value })}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  ) : (
                    <Input
                      id={inputId}
                      type={field.type === "integer" ? "number" : "text"}
                      min={field.minimum ?? undefined}
                      max={field.maximum ?? undefined}
                      step={field.type === "integer" ? 1 : undefined}
                      value={typeof draft === "string" ? draft : ""}
                      onChange={(event) => onChange(field.name, event.target.value)}
                      disabled={disabled}
                      placeholder={
                        field.default === null ? t("rag.chunkers.emptyIsDefault") : undefined
                      }
                    />
                  )}
                </>
              )}
              <p
                className={
                  isInvalid ? "text-destructive text-xs" : "text-muted-foreground text-xs"
                }
              >
                {isInvalid
                  ? t("rag.chunkers.invalidOption", { field: label })
                  : hint}
              </p>
            </div>
          );
        })}
      </div>
    </div>
  );
}
