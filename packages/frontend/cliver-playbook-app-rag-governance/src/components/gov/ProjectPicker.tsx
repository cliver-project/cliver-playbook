import { useTranslation } from "react-i18next";
import { useSearchParams } from "react-router-dom";

import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "cliver-playbook-app-basic/components/ui/select.tsx";

import { useCurrentProject } from "cliver-playbook-app-rag-governance/components/gov/useProject.ts";

/**
 * The project switcher, bound to the `?project=` search parameter.
 *
 * Changing it rewrites the parameter so the page — and every card that links
 * to another governance page — stays on one project without shared client
 * state.
 */
export function ProjectPicker() {
  const { t } = useTranslation();
  const { project, projectId } = useCurrentProject();
  const [, setParams] = useSearchParams();

  return (
    <Select
      value={projectId ?? undefined}
      onValueChange={(value) => {
        setParams((current) => {
          const next = new URLSearchParams(current);
          next.set("project", value);
          return next;
        });
      }}
    >
      <SelectTrigger className="w-64" aria-label={t("gov.common.project")}>
        <SelectValue placeholder={t("gov.common.project")} />
      </SelectTrigger>
      <SelectContent>
        {/* The picker renders exactly one item per project; the id is the
            value so the fallback logic in useCurrentProject stays the only
            place that decides "which project". */}
        {projectId ? (
          <SelectItem value={projectId}>{project?.name ?? projectId}</SelectItem>
        ) : null}
      </SelectContent>
    </Select>
  );
}
