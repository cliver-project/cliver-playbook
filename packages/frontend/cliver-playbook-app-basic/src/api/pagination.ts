/**
 * The shared pagination contract.
 *
 * Mirrors `Page[T]` in the backend's basic package: `items` is the current
 * window, `total` counts the full filtered set, and `limit`/`offset` echo the
 * window the server applied. API modules type paginated responses as
 * `Page<Row>` and pages consume them through `usePagedQuery`.
 */

export interface Page<T> {
  items: T[];
  total: number;
  limit: number;
  offset: number;
}

/** The window request a paged endpoint accepts. */
export interface PageRequest {
  limit: number;
  offset: number;
}
