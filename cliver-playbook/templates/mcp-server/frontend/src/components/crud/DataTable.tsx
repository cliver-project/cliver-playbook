import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";

/**
 * Generic read-only table with loading and empty states — the display half of
 * the entity-CRUD pattern (src/components/crud/useCrudQueries.ts owns the
 * data half). Columns are plain render functions, so any cell content
 * (badges, truncation, buttons) is possible without a config DSL.
 */

export interface DataTableColumn<T> {
  /** Stable key for the column's React elements. */
  key: string;
  header: ReactNode;
  render: (row: T) => ReactNode;
  /** Extra classes for both the th and td of this column. */
  className?: string;
}

export function DataTable<T>({
  columns,
  rows,
  rowKey,
  isLoading,
  emptyLabel,
}: {
  columns: DataTableColumn<T>[];
  rows: T[] | undefined;
  rowKey: (row: T) => string | number;
  isLoading: boolean;
  /** Shown instead of "not found" when the list is simply empty. */
  emptyLabel?: string;
}) {
  const { t } = useTranslation();

  return (
    <div className="rounded-lg border">
      <Table>
        <TableHeader>
          <TableRow>
            {columns.map((column) => (
              <TableHead key={column.key} className={column.className}>
                {column.header}
              </TableHead>
            ))}
          </TableRow>
        </TableHeader>
        <TableBody>
          {isLoading ? (
            <TableRow>
              <TableCell colSpan={columns.length} className="text-muted-foreground">
                {t("common.loading")}
              </TableCell>
            </TableRow>
          ) : rows && rows.length > 0 ? (
            rows.map((row) => (
              <TableRow key={rowKey(row)}>
                {columns.map((column) => (
                  <TableCell key={column.key} className={column.className}>
                    {column.render(row)}
                  </TableCell>
                ))}
              </TableRow>
            ))
          ) : (
            <TableRow>
              <TableCell colSpan={columns.length} className="text-muted-foreground">
                {emptyLabel ?? t("common.notFound")}
              </TableCell>
            </TableRow>
          )}
        </TableBody>
      </Table>
    </div>
  );
}
