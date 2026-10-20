import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";

import { useAuth } from "cliver-playbook-app-user/components/auth/AuthContext.tsx";
import { ConfirmDialog } from "cliver-playbook-app-basic/components/ConfirmDialog.tsx";
import { Badge } from "cliver-playbook-app-basic/components/ui/badge.tsx";
import { Button } from "cliver-playbook-app-basic/components/ui/button.tsx";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "cliver-playbook-app-basic/components/ui/table.tsx";
import { apiErrorMessage } from "cliver-playbook-app-basic/api/client.ts";
import {
  listOauthClients,
  listOauthGrants,
  revokeOauthGrant,
  type OauthGrantInfo,
} from "cliver-playbook-app-user/api/auth.ts";

/**
 * OAuth provider administration: which clients have registered (DCR is open
 * by design, so this listing is the operator's only visibility into who has
 * ever connected) and which agents can act as which user RIGHT NOW (live
 * grants = unrevoked, unexpired refresh-token chains).
 *
 * Revoking a grant kills the whole (user × client) relationship: every
 * refresh chain AND the OAuth access tokens minted from it, so the agent's
 * in-flight requests die too. The Revoke button is hidden without
 * `oauth:revoke` — display gating only; the server enforces regardless.
 */
export default function OAuthPage() {
  const { t } = useTranslation();
  const { hasPerm } = useAuth();
  const queryClient = useQueryClient();

  const grants = useQuery({ queryKey: ["oauth-grants"], queryFn: listOauthGrants });
  const clients = useQuery({ queryKey: ["oauth-clients"], queryFn: listOauthClients });

  const [revoking, setRevoking] = useState<OauthGrantInfo | null>(null);

  const revoke = useMutation({
    mutationFn: (grant: OauthGrantInfo) => revokeOauthGrant(grant.user_id, grant.client_id),
    onSuccess: () => {
      toast.success(t("admin.oauth.revoked"));
      setRevoking(null);
      void queryClient.invalidateQueries({ queryKey: ["oauth-grants"] });
    },
    onError: (error) => toast.error(apiErrorMessage(error)),
  });

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">{t("admin.oauth.title")}</h1>
      </div>

      {/* ------------------------------------------------------------------ */}
      {/* Active grants                                                       */}
      {/* ------------------------------------------------------------------ */}
      <section className="space-y-3">
        <div>
          <h2 className="text-lg font-medium">{t("admin.oauth.grantsTitle")}</h2>
          <p className="text-muted-foreground text-sm">{t("admin.oauth.grantsDescription")}</p>
        </div>
        <div className="rounded-lg border">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>{t("admin.oauth.user")}</TableHead>
                <TableHead>{t("admin.oauth.client")}</TableHead>
                <TableHead>{t("admin.oauth.scopes")}</TableHead>
                <TableHead>{t("admin.oauth.granted")}</TableHead>
                <TableHead>{t("admin.oauth.expires")}</TableHead>
                <TableHead className="w-10" />
              </TableRow>
            </TableHeader>
            <TableBody>
              {grants.isLoading ? (
                <TableRow>
                  <TableCell colSpan={6} className="text-muted-foreground">
                    {t("common.loading")}
                  </TableCell>
                </TableRow>
              ) : grants.data && grants.data.length > 0 ? (
                grants.data.map((grant) => (
                  <TableRow key={grant.id}>
                    <TableCell className="font-medium">{grant.username}</TableCell>
                    <TableCell>
                      <div>{grant.client_name}</div>
                      <div className="text-muted-foreground font-mono text-xs">
                        {grant.client_id}
                      </div>
                    </TableCell>
                    <TableCell>
                      <div className="flex flex-wrap gap-1">
                        {grant.scopes.length > 0 ? (
                          grant.scopes.map((scope) => (
                            <Badge key={scope} variant="outline">
                              {scope}
                            </Badge>
                          ))
                        ) : (
                          <span className="text-muted-foreground text-xs">—</span>
                        )}
                      </div>
                    </TableCell>
                    <TableCell className="text-muted-foreground">
                      {new Date(grant.granted_at).toLocaleString()}
                    </TableCell>
                    <TableCell className="text-muted-foreground">
                      {new Date(grant.expires_at).toLocaleString()}
                    </TableCell>
                    <TableCell>
                      {hasPerm("oauth:revoke") ? (
                        <Button
                          variant="ghost"
                          size="sm"
                          className="text-destructive hover:text-destructive"
                          onClick={() => setRevoking(grant)}
                        >
                          {t("admin.oauth.revoke")}
                        </Button>
                      ) : null}
                    </TableCell>
                  </TableRow>
                ))
              ) : (
                <TableRow>
                  <TableCell colSpan={6} className="text-muted-foreground">
                    {t("admin.oauth.grantsEmpty")}
                  </TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
        </div>
      </section>

      {/* ------------------------------------------------------------------ */}
      {/* Registered clients                                                  */}
      {/* ------------------------------------------------------------------ */}
      <section className="space-y-3">
        <div>
          <h2 className="text-lg font-medium">{t("admin.oauth.clientsTitle")}</h2>
          <p className="text-muted-foreground text-sm">{t("admin.oauth.clientsDescription")}</p>
        </div>
        <div className="rounded-lg border">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>{t("admin.oauth.client")}</TableHead>
                <TableHead>{t("admin.oauth.clientId")}</TableHead>
                <TableHead>{t("admin.oauth.redirectUris")}</TableHead>
                <TableHead>{t("admin.oauth.grantTypes")}</TableHead>
                <TableHead>{t("admin.oauth.registered")}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {clients.isLoading ? (
                <TableRow>
                  <TableCell colSpan={5} className="text-muted-foreground">
                    {t("common.loading")}
                  </TableCell>
                </TableRow>
              ) : clients.data && clients.data.length > 0 ? (
                clients.data.map((client) => (
                  <TableRow key={client.client_id}>
                    <TableCell className="font-medium">{client.client_name}</TableCell>
                    <TableCell className="text-muted-foreground font-mono text-xs">
                      {client.client_id}
                    </TableCell>
                    <TableCell>
                      <div className="flex flex-col gap-0.5">
                        {client.redirect_uris.length > 0 ? (
                          client.redirect_uris.map((uri) => (
                            <span key={uri} className="font-mono text-xs break-all">
                              {uri}
                            </span>
                          ))
                        ) : (
                          <span className="text-muted-foreground text-xs">—</span>
                        )}
                      </div>
                    </TableCell>
                    <TableCell>
                      <div className="flex flex-wrap gap-1">
                        {client.grant_types.length > 0 ? (
                          client.grant_types.map((grantType) => (
                            <Badge key={grantType} variant="outline">
                              {grantType}
                            </Badge>
                          ))
                        ) : (
                          <span className="text-muted-foreground text-xs">—</span>
                        )}
                      </div>
                    </TableCell>
                    <TableCell className="text-muted-foreground">
                      {new Date(client.created_at).toLocaleString()}
                    </TableCell>
                  </TableRow>
                ))
              ) : (
                <TableRow>
                  <TableCell colSpan={5} className="text-muted-foreground">
                    {t("admin.oauth.clientsEmpty")}
                  </TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
        </div>
      </section>

      <ConfirmDialog
        open={revoking !== null}
        onOpenChange={(open) => !open && setRevoking(null)}
        title={t("admin.oauth.revokeTitle", {
          username: revoking?.username ?? "",
          client: revoking?.client_name ?? "",
        })}
        description={t("admin.oauth.revokeConfirm")}
        confirmLabel={t("admin.oauth.revoke")}
        pending={revoke.isPending}
        onConfirm={() => revoking && revoke.mutate(revoking)}
      />
    </div>
  );
}
