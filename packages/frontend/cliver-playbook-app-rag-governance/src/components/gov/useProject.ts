import { useQuery } from "@tanstack/react-query";
import { useSearchParams } from "react-router-dom";

import { listProjects, type Project } from "cliver-playbook-app-rag-governance/api/governance.ts";

/**
 * The project every governance page works on.
 *
 * The demo runs one project, but the pages must not hardcode it: the id
 * travels in the `?project=` search parameter so an overview card's link
 * opens the right context, and the first project is the fallback for a bare
 * URL. Returns the resolved project (or null while loading / when none
 * exists) plus the resolved id used in links.
 */
export function useCurrentProject(): {
  project: Project | null;
  projectId: string | null;
  isLoading: boolean;
  isError: boolean;
  error: unknown;
} {
  const [params] = useSearchParams();
  const requested = params.get("project");
  const projects = useQuery({ queryKey: ["gov-projects"], queryFn: listProjects });

  const items = projects.data?.items ?? [];
  const project =
    (requested ? items.find((item) => item.id === requested) : undefined) ?? items[0] ?? null;

  return {
    project,
    projectId: project?.id ?? null,
    isLoading: projects.isLoading,
    isError: projects.isError,
    error: projects.error,
  };
}
