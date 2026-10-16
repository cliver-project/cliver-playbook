import { api } from "./client";

/**
 * Identity-domain API calls (user-management template).
 *
 * Thin typed wrappers — no state, no caching; TanStack Query handles server
 * state at the call sites. Shapes mirror app/schemas/auth.py exactly.
 */

export interface CurrentUser {
  id: number;
  username: string;
  email: string | null;
  phone: string | null;
  display_name: string;
  is_active: boolean;
  must_change_password: boolean;
  created_at: string;
  role_codes: string[];
  /** Flattened permission codes; display-only gating (server enforces). */
  permissions: string[];
}

export interface LoginResult {
  token: string;
  must_change_password: boolean;
  user: CurrentUser;
}

export interface Role {
  id: number;
  code: string;
  name: string;
  description: string;
  is_system: boolean;
  created_at: string;
  permission_codes: string[];
}

export interface PermissionInfo {
  code: string;
  name: string;
  group: string;
}

export interface AuditLogRow {
  id: number;
  created_at: string;
  user_id: number | null;
  username: string;
  event: string;
  target: string;
  ok: boolean;
  error: string;
  detail: Record<string, unknown>;
  ip: string;
  user_agent: string;
}

export interface AuditLogPage {
  items: AuditLogRow[];
  total: number;
}

// ---------------------------------------------------------------------------
// Session
// ---------------------------------------------------------------------------

export async function login(username: string, password: string): Promise<LoginResult> {
  const { data } = await api.post<LoginResult>("/auth/login", { username, password });
  return data;
}

export async function logout(): Promise<void> {
  await api.post("/auth/logout");
}

export async function fetchMe(): Promise<CurrentUser> {
  const { data } = await api.get<{ user: CurrentUser }>("/auth/me");
  return data.user;
}

export async function changePassword(oldPassword: string, newPassword: string): Promise<LoginResult> {
  const { data } = await api.post<LoginResult>("/auth/change-password", {
    old_password: oldPassword,
    new_password: newPassword,
  });
  return data;
}

/** Self-service profile edit. Send only the fields to change; an explicit
 * empty string clears email/phone (server maps "" -> null). */
export interface ProfileUpdateInput {
  email?: string | null;
  phone?: string | null;
  display_name?: string;
}

export async function updateProfile(input: ProfileUpdateInput): Promise<CurrentUser> {
  const { data } = await api.patch<{ user: CurrentUser }>("/auth/profile", input);
  return data.user;
}

// ---------------------------------------------------------------------------
// OIDC client login (SSO)
// ---------------------------------------------------------------------------

export interface OAuthProviderButton {
  key: string;
  label: string;
}

export async function listOAuthProviders(): Promise<OAuthProviderButton[]> {
  const { data } = await api.get<{ providers: OAuthProviderButton[] }>("/auth/oauth/providers");
  return data.providers;
}

/** Full URL that starts the OIDC redirect dance (navigate the whole tab). */
export function oauthLoginUrl(providerKey: string): string {
  return `${api.defaults.baseURL ?? ""}/auth/oauth/${providerKey}/login`;
}

// ---------------------------------------------------------------------------
// OAuth 2.1 authorize page (agent consent hand-off)
// ---------------------------------------------------------------------------

export interface AuthorizeInfo {
  client_name: string;
  scopes: string[];
}

export async function fetchAuthorizeInfo(blob: string): Promise<AuthorizeInfo> {
  const { data } = await api.get<AuthorizeInfo>("/auth/oauth/authorize/info", {
    params: { blob },
  });
  return data;
}

/** Submit credentials for an agent's authorization; returns the redirect URL
 * carrying code+state back to the agent's callback — navigate the whole tab. */
export async function submitAuthorize(
  blob: string,
  username: string,
  password: string,
): Promise<string> {
  const { data } = await api.post<{ redirect_url: string }>("/auth/oauth/authorize", {
    blob,
    username,
    password,
  });
  return data.redirect_url;
}

// ---------------------------------------------------------------------------
// Admin: users
// ---------------------------------------------------------------------------

export async function listUsers(q?: string): Promise<CurrentUser[]> {
  const { data } = await api.get<CurrentUser[]>("/admin/users", { params: q ? { q } : {} });
  return data;
}

export interface UserCreateInput {
  username: string;
  password: string;
  email?: string | null;
  phone?: string | null;
  display_name?: string;
  role_ids: number[];
  must_change_password?: boolean;
}

export async function createUser(input: UserCreateInput): Promise<CurrentUser> {
  const { data } = await api.post<CurrentUser>("/admin/users", input);
  return data;
}

export interface UserUpdateInput {
  email?: string | null;
  phone?: string | null;
  display_name?: string;
  is_active?: boolean;
  role_ids?: number[];
}

export async function updateUser(id: number, input: UserUpdateInput): Promise<CurrentUser> {
  const { data } = await api.patch<CurrentUser>(`/admin/users/${id}`, input);
  return data;
}

export async function deleteUser(id: number): Promise<void> {
  await api.delete(`/admin/users/${id}`);
}

export async function resetPassword(id: number, newPassword: string): Promise<void> {
  await api.post(`/admin/users/${id}/reset-password`, { new_password: newPassword });
}

export async function forceLogout(id: number): Promise<void> {
  await api.post(`/admin/users/${id}/force-logout`);
}

// ---------------------------------------------------------------------------
// Admin: roles + permission catalog
// ---------------------------------------------------------------------------

export async function listRoles(): Promise<Role[]> {
  const { data } = await api.get<Role[]>("/admin/roles");
  return data;
}

export interface RoleInput {
  code: string;
  name: string;
  description?: string;
  permission_codes: string[];
}

export async function createRole(input: RoleInput): Promise<Role> {
  const { data } = await api.post<Role>("/admin/roles", input);
  return data;
}

export interface RoleUpdateInput {
  name?: string;
  description?: string;
  permission_codes?: string[];
}

export async function updateRole(id: number, input: RoleUpdateInput): Promise<Role> {
  const { data } = await api.patch<Role>(`/admin/roles/${id}`, input);
  return data;
}

export async function deleteRole(id: number): Promise<void> {
  await api.delete(`/admin/roles/${id}`);
}

export async function listPermissions(): Promise<PermissionInfo[]> {
  const { data } = await api.get<PermissionInfo[]>("/admin/permissions");
  return data;
}

// ---------------------------------------------------------------------------
// Admin: OAuth provider (registered clients + live grants)
// ---------------------------------------------------------------------------

/** A dynamically registered client (RFC 7591). The registration secret is
 * never exposed by the listing endpoint. */
export interface OauthClientInfo {
  client_id: string;
  client_name: string;
  redirect_uris: string[];
  grant_types: string[];
  created_at: string;
}

/** One live grant: an unrevoked, unexpired refresh-token chain a user
 * authorized for a client. */
export interface OauthGrantInfo {
  id: number;
  user_id: number;
  username: string;
  client_id: string;
  client_name: string;
  scopes: string[];
  granted_at: string;
  expires_at: string;
}

export async function listOauthClients(): Promise<OauthClientInfo[]> {
  const { data } = await api.get<OauthClientInfo[]>("/admin/oauth/clients");
  return data;
}

export async function listOauthGrants(): Promise<OauthGrantInfo[]> {
  const { data } = await api.get<OauthGrantInfo[]>("/admin/oauth/grants");
  return data;
}

/** Revokes every live grant for a (user, client) pair — refresh chains and
 * OAuth access tokens both, so the agent's current requests die too.
 * Idempotent server-side; returns how many refresh tokens were revoked. */
export async function revokeOauthGrant(userId: number, clientId: string): Promise<number> {
  const { data } = await api.post<{ ok: boolean; revoked_refresh_tokens: number }>(
    "/admin/oauth/grants/revoke",
    { user_id: userId, client_id: clientId },
  );
  return data.revoked_refresh_tokens;
}

// ---------------------------------------------------------------------------
// Admin: audit log
// ---------------------------------------------------------------------------

export interface AuditQuery {
  event?: string;
  username?: string;
  limit?: number;
  offset?: number;
}

export async function listAudit(query: AuditQuery = {}): Promise<AuditLogPage> {
  const { data } = await api.get<AuditLogPage>("/admin/audit", { params: query });
  return data;
}
