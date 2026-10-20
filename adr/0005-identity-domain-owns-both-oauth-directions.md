# ADR-0005: The identity domain owns both OAuth directions

**Status:** Accepted (2026-10-15; write-up 2026-10-17 — the code cites this ADR from
`auth/oauth21.py`, `auth/oidc.py`, the settings and the models). Amended 2026-10-15
(multi-provider OIDC login), 2026-10-16 (linked accounts), 2026-10-16 (root mount,
after the package split).
**Context:** The app sits on both sides of OAuth: agents (MCP clients, CLIs) need to
obtain a credential *from* it, and people sign in *through* external identity
providers. Both concern the same subjects — users, credentials, revocation, audit —
and both had a tempting alternative: put the authorization server in the MCP package
(it is agents that use it), and put the login flow in the frontend (SPA OIDC
libraries exist).

## Decision

1. **The OAuth 2.1 authorization server lives in the identity package** (`auth/oauth21.py`),
   with no knowledge of MCP: authorization code + PKCE S256, RFC 7591 dynamic client
   registration, RFC 9728 protected-resource metadata, refresh rotation and RFC 7009
   revocation. The MCP package points its resource metadata at it; it does not own it.
   Swapping the MCP surface for a different agent protocol would not touch the
   authorization server.

2. **Access tokens are rows in `auth_tokens`** (`client_id` set, TTL) — the same table
   and the same revocation path as everything else (ADR-0004). "Revoke this agent" is
   an operation that already existed for browser sessions.

3. **Refresh tokens rotate one-time, with a replay policy.** `replaced_by_id` is the
   rotation pointer and it distinguishes the two ways a refresh token goes stale:
   revoked via `/revoke` (pointer NULL — silently invalid) versus consumed by a
   rotation and then replayed (pointer set — the defense fires). Replay inside a short
   grace window is audited as a suspected network retry; beyond it the whole
   (user, client) family is revoked, as OAuth 2.1 requires.

4. **The app is a plain OIDC *client* of external providers** (`auth/oidc.py`):
   authorization code + PKCE, state in an HMAC-signed HttpOnly cookie (stateless — no
   pending-login table), identification via the **userinfo endpoint**. The `id_token`
   is never parsed: it arrived over TLS from the token endpoint in response to our
   one-time code and verifier, so it is no more trustworthy than the userinfo payload
   and costs a JWT/JWKS dependency plus key-rotation handling. **The client secret
   stays server-side** — the browser never speaks to the IdP, which is the whole
   reason the SPA does not use an OIDC library.

5. **Providers are configuration, not code** (amendment 2026-10-15). The registry is
   built from a nested settings block; each provider is either discovery-based
   (`issuer`) or explicit-endpoint (`authorize_url` / `token_url` / `userinfo_url`,
   for OAuth2 services with no discovery document), and `subject_claim` maps the
   provider's stable identifier when it is not `sub` (numeric ids included — the
   stored subject is a string). Adding a provider is a config change; the login page
   renders one button per enabled provider from the labels in that block. Presets
   ship disabled: enabling a provider is a deployment decision.

6. **Identities are linkable, and the last credential is protected** (amendment
   2026-10-16). A signed blob carries `mode=login|link` (plus the user id when
   linking), so the same callback serves both flows; linking reuses the login
   redirect URI and **never issues a token**. Unlinking is server-guarded: an account
   whose only credential is an OIDC identity (no password) cannot unlink its last
   identity — the UI greys the action out, the server refuses it (409), and the state
   is decided from `password_hash` and the remaining identity rows, not from the
   client.

7. **The authorization server is mounted at the root, with no mount-path parameter**
   (amendment 2026-10-16, found while replacing the MCP sub-app with a router route —
   ADR-0017). Well-known and protected-resource metadata paths are anchored at the
   origin by specification, so a prefixed mount could not serve them; the routes are
   inserted ahead of everything else, which is also why the MCP endpoint at `/mcp` is
   reachable under `include_router` without shadowing them.

## Consequences

- One identity surface to audit: login, linking, unlinking and agent authorization all
  write to `audit_logs` and all end at the same token table.
- The public-first (`userinfo`) choice means a provider that returns only an `id_token`
  and no userinfo endpoint is not supported — a documented limitation, acceptable for
  the providers in scope, and the place to reverse this decision if it ever bites.
- Deployed behind a proxy that rewrites `Host`, the issuer must be pinned explicitly:
  the `iss` an agent compares is byte-for-byte, including a trailing slash.

## Alternatives considered

- **The MCP package owning the authorization server**: rejected — the coupling is
  backwards (a protocol's needs would drive the identity model), and a second agent
  protocol would fork it.
- **A separate `oauth_access_tokens` table**: rejected — see ADR-0004.
- **`oidc-client-ts` or similar in the SPA**: rejected — it puts the client secret (or
  a public-client flow with its own constraints) in the browser, and the backend
  would then have to accept tokens it cannot verify without JWKS.
- **Validating the `id_token` instead of calling userinfo**: rejected — an extra
  dependency and key-rotation homework to learn nothing new, given the code flow.
- **A pending-login table for OAuth state**: rejected — the HMAC-signed cookie is
  stateless, and its signature is what makes a tampered `redirect_uri` or injected
  `code_challenge` unable to survive the round trip.
- **Per-provider login code**: rejected — it multiplies the flow by the number of
  providers and makes each new one a code change; the registry normalizes
  discovery-based and explicit-endpoint providers into one shape the flow reads.
