import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { listAudit } from "@/api/auth";

/**
 * Read-only audit trail viewer (audit:read). Every login, password change,
 * admin mutation, and OAuth grant/revoke lands here — the trail is the
 * system's memory of who did what, which is why it is queryable but never
 * editable or deletable through the API.
 *
 * Filters are exact-match on event, substring on username; pagination is
 * simple offset-based (newest first), enough for administrative inspection.
 */

const PAGE_SIZE = 50;

export default function AuditPage() {
  const { t } = useTranslation();
  const [event, setEvent] = useState("");
  const [username, setUsername] = useState("");
  const [offset, setOffset] = useState(0);

  const page = useQuery({
    queryKey: ["audit", event, username, offset],
    queryFn: () =>
      listAudit({
        event: event || undefined,
        username: username || undefined,
        limit: PAGE_SIZE,
        offset,
      }),
    placeholderData: (prev) => prev, // keep rows on the screen while refetching
  });

  const total = page.data?.total ?? 0;

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3">
        <h1 className="text-2xl font-semibold tracking-tight">{t("admin.audit.title")}</h1>
        <div className="ml-auto flex items-center gap-2">
          <Input
            placeholder={t("admin.audit.filterEvent")}
            value={event}
            onChange={(e) => {
              setEvent(e.target.value);
              setOffset(0);
            }}
            className="w-48 font-mono text-sm"
          />
          <Input
            placeholder={t("admin.audit.filterUsername")}
            value={username}
            onChange={(e) => {
              setUsername(e.target.value);
              setOffset(0);
            }}
            className="w-40"
          />
        </div>
      </div>

      <div className="rounded-lg border">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>{t("admin.audit.when")}</TableHead>
              <TableHead>{t("admin.audit.event")}</TableHead>
              <TableHead>{t("admin.audit.user")}</TableHead>
              <TableHead>{t("admin.audit.target")}</TableHead>
              <TableHead>{t("admin.audit.outcome")}</TableHead>
              <TableHead>{t("admin.audit.detail")}</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {page.isLoading ? (
              <TableRow>
                <TableCell colSpan={6} className="text-muted-foreground">
                  {t("common.loading")}
                </TableCell>
              </TableRow>
            ) : page.data && page.data.items.length > 0 ? (
              page.data.items.map((row) => (
                <TableRow key={row.id}>
                  <TableCell className="text-muted-foreground whitespace-nowrap text-xs">
                    {new Date(row.created_at).toLocaleString()}
                  </TableCell>
                  <TableCell className="font-mono text-xs">{row.event}</TableCell>
                  <TableCell className="text-sm">{row.username || "—"}</TableCell>
                  <TableCell className="text-muted-foreground max-w-44 truncate text-xs">
                    {row.target || "—"}
                  </TableCell>
                  <TableCell>
                    {row.ok ? (
                      <Badge variant="secondary">{t("admin.audit.ok")}</Badge>
                    ) : (
                      <Badge variant="destructive">{row.error || t("admin.audit.failed")}</Badge>
                    )}
                  </TableCell>
                  <TableCell className="text-muted-foreground max-w-64 truncate font-mono text-xs">
                    {Object.keys(row.detail).length > 0 ? JSON.stringify(row.detail) : "—"}
                  </TableCell>
                </TableRow>
              ))
            ) : (
              <TableRow>
                <TableCell colSpan={6} className="text-muted-foreground">
                  {t("common.notFound")}
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>
      </div>

      <div className="flex items-center justify-between">
        <p className="text-muted-foreground text-xs">
          {t("admin.audit.range", {
            from: total === 0 ? 0 : offset + 1,
            to: Math.min(offset + PAGE_SIZE, total),
            total,
          })}
        </p>
        <div className="flex gap-2">
          <Button
            variant="outline"
            size="sm"
            disabled={offset === 0 || page.isFetching}
            onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
          >
            {t("admin.audit.prev")}
          </Button>
          <Button
            variant="outline"
            size="sm"
            disabled={offset + PAGE_SIZE >= total || page.isFetching}
            onClick={() => setOffset(offset + PAGE_SIZE)}
          >
            {t("admin.audit.next")}
          </Button>
        </div>
      </div>
    </div>
  );
}
