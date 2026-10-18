import { useTranslation } from "react-i18next";

import type { StageOption } from "cliver-playbook-app-rag/api/rag.ts";
import { Label } from "cliver-playbook-app-basic/components/ui/label.tsx";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "cliver-playbook-app-basic/components/ui/select.tsx";

/**
 * One stage dropdown, fed by the server's stage catalog.
 *
 * The option list is never hardcoded: it is whatever the server's registries
 * currently contain, so a newly registered implementation shows up here with
 * no frontend change. `model_id` and `dim` are appended where the stage
 * exposes them, which is what lets a user tell `stub` (64-d) from a production
 * embedder (1024-d) before uploading.
 */
export interface StageSelectorProps {
  id: string;
  label: string;
  value: string;
  options: StageOption[];
  onChange: (value: string) => void;
  disabled?: boolean;
  description?: string;
}

export function StageSelector({
  id,
  label,
  value,
  options,
  onChange,
  disabled = false,
  description,
}: StageSelectorProps) {
  const { t } = useTranslation();

  return (
    <div className="space-y-1.5">
      <Label htmlFor={id}>{label}</Label>
      <Select value={value} onValueChange={onChange} disabled={disabled}>
        <SelectTrigger id={id} className="w-full">
          <SelectValue placeholder={t("rag.common.selectStage")} />
        </SelectTrigger>
        <SelectContent>
          {options.map((option) => (
            <SelectItem key={option.name} value={option.name}>
              {option.name}
              {option.dim ? ` · ${option.dim}d` : ""}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      {description ? (
        <p className="text-muted-foreground text-xs">{description}</p>
      ) : null}
    </div>
  );
}
