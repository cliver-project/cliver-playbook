import { useMutation, useQuery, useQueryClient, type QueryKey } from "@tanstack/react-query";
import { toast } from "sonner";

import { apiErrorMessage } from "@/api/client";

/**
 * Generic entity-CRUD hook — the reuse point for "manage a table of things"
 * pages (see src/pages/ItemsPage.tsx for the reference composition).
 *
 * Owns everything that is the same for every entity:
 * - the list query under `queryKey`
 * - create/update/delete mutations that invalidate that key on success
 * - error toasts (the axios interceptor already extracts the message)
 *
 * Everything entity-specific — field forms, columns, row actions — stays in
 * the page component, which is the honest boundary: forms and tables differ
 * per entity, query plumbing does not. An entity without some operation
 * (read-only, no delete, ...) simply doesn't use that mutation; point it at
 * the same API module and leave the unused function out of the page.
 */

export interface CrudMessages {
  /** Success toasts; already translated by the caller (it owns i18n). */
  created?: string;
  updated?: string;
  deleted?: string;
}

export interface CrudConfig<T, CreateInput, UpdateInput> {
  /** Cache key shared by the list query and every invalidation below. */
  queryKey: QueryKey;
  /** Full CRUD surface, mirroring the scaffold's resource-router pattern. */
  list: () => Promise<T[]>;
  create: (input: CreateInput) => Promise<T>;
  update: (id: number, input: UpdateInput) => Promise<T>;
  remove: (id: number) => Promise<void>;
  messages?: CrudMessages;
  /** Called after EVERY successful mutation — the natural place to close
   * whatever create/edit/delete dialog the page has open. On failure the
   * dialog stays put (the error is already toasted); dismissing it is the
   * user's call. */
  onSuccess?: () => void;
}

export function useCrudQueries<T, CreateInput, UpdateInput>(
  config: CrudConfig<T, CreateInput, UpdateInput>,
) {
  const queryClient = useQueryClient();
  const onError = (error: unknown) => toast.error(apiErrorMessage(error));
  const succeeded = () => {
    config.onSuccess?.();
  };

  const items = useQuery({ queryKey: config.queryKey, queryFn: config.list });
  const invalidate = () => queryClient.invalidateQueries({ queryKey: config.queryKey });

  const create = useMutation({
    mutationFn: config.create,
    onSuccess: () => {
      if (config.messages?.created) toast.success(config.messages.created);
      succeeded();
      invalidate();
    },
    onError,
  });

  const update = useMutation({
    mutationFn: ({ id, input }: { id: number; input: UpdateInput }) =>
      config.update(id, input),
    onSuccess: () => {
      if (config.messages?.updated) toast.success(config.messages.updated);
      succeeded();
      invalidate();
    },
    onError,
  });

  const remove = useMutation({
    mutationFn: config.remove,
    onSuccess: () => {
      if (config.messages?.deleted) toast.success(config.messages.deleted);
      succeeded();
      invalidate();
    },
    onError,
  });

  return { items, create, update, remove };
}
