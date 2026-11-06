import { useState } from "react";
import {
  keepPreviousData,
  useQuery,
  type QueryKey,
  type UseQueryResult,
} from "@tanstack/react-query";

import type { Page, PageRequest } from "cliver-playbook-app-basic/api/pagination.ts";

export interface UsePagedQueryOptions<T> {
  /** Filter identity — the hook appends the current window to this key. */
  queryKey: QueryKey;
  /** Fetch one window; the hook owns `limit` and `offset`. */
  queryFn: (request: PageRequest) => Promise<Page<T>>;
  /** Rows per page. Defaults to the backend's shared default (50). */
  pageSize?: number;
  /**
   * Changing this value returns to the first page. Pass the serialized
   * filter state (not an object identity) so edits reset the offset in the
   * same render, before the query fires.
   */
  resetKey?: string | number;
  enabled?: boolean;
}

export interface PagedQuery<T> {
  /** The raw TanStack result, for refetch/error details. */
  query: UseQueryResult<Page<T>>;
  items: T[];
  total: number;
  offset: number;
  pageSize: number;
  isLoading: boolean;
  isFetching: boolean;
  error: unknown;
  setOffset: (offset: number) => void;
  prevPage: () => void;
  nextPage: () => void;
  canPrev: boolean;
  canNext: boolean;
  /** 1-based row range of the current window (`0..0` when empty). */
  from: number;
  to: number;
}

/**
 * Offset pagination for a `Page<T>` endpoint.
 *
 * Owns the offset state and keeps the previous page on screen while the next
 * one loads. A filter change passed as `resetKey` rewinds to the first page
 * during render, so no stale-offset request is sent. When the current page
 * becomes empty because rows were deleted, the hook steps back one page
 * instead of leaving the viewer on a blank table.
 */
export function usePagedQuery<T>({
  queryKey,
  queryFn,
  pageSize = 50,
  resetKey,
  enabled,
}: UsePagedQueryOptions<T>): PagedQuery<T> {
  const [offset, setOffsetState] = useState(0);
  const [seenResetKey, setSeenResetKey] = useState(resetKey);

  // Render-phase adjustment (React's documented pattern): the stale-offset
  // query never commits, and the new page-one query runs once.
  if (resetKey !== seenResetKey) {
    setSeenResetKey(resetKey);
    setOffsetState(0);
  }

  const query = useQuery({
    queryKey: [...queryKey, { limit: pageSize, offset }],
    queryFn: () => queryFn({ limit: pageSize, offset }),
    placeholderData: keepPreviousData,
    enabled,
  });

  const total = query.data?.total ?? 0;

  // Same render-phase adjustment: if rows were deleted out from under the
  // current window, step back instead of showing a blank table.
  if (
    offset > 0 &&
    query.data !== undefined &&
    query.data.items.length === 0 &&
    !query.isPlaceholderData
  ) {
    setOffsetState(Math.max(0, offset - pageSize));
  }

  const setOffset = (next: number) => setOffsetState(Math.max(0, next));

  return {
    query,
    items: query.data?.items ?? [],
    total,
    offset,
    pageSize,
    isLoading: query.isLoading,
    isFetching: query.isFetching,
    error: query.error,
    setOffset,
    prevPage: () => setOffsetState(Math.max(0, offset - pageSize)),
    nextPage: () => setOffsetState(offset + pageSize),
    canPrev: offset > 0,
    canNext: offset + pageSize < total,
    from: total === 0 ? 0 : offset + 1,
    to: Math.min(offset + pageSize, total),
  };
}
