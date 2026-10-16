# ADR-0004: One `auth_tokens` table, three token kinds, and predicate discipline

**Status:** Accepted (2026-10-15; write-up 2026-10-17).
**Context:** The system issues credentials to three very different callers: a browser
session (a person, 30-day lifetime), a long-lived static token an operator pastes into
an agent's configuration (no expiry, revocable, rotatable), and OAuth 2.1 access
tokens for registered clients (short TTL, refreshable). Storing them in three tables
would mean three issuance flows, three revocation paths and three places for a
force-logout to miss.

## Decision

1. **One physical table, three logical kinds**, discriminated by which columns are set:

   | kind | `client_id` | `expires_at` | `label` |
   | --- | --- | --- | --- |
   | web session | NULL | now + TTL | empty |
   | static token | NULL | NULL (never) | non-empty (e.g. an agent name) |
   | OAuth access | set | now + TTL | empty |

2. **Tokens are opaque and stored hashed.** A 256-bit random value, never a claim
   container; only its SHA-256 hex digest is stored, so a database leak yields no
   usable credential. Everything a request needs (user, roles, permissions, expiry)
   is resolved from the database on every request — one indexed lookup, and in
   exchange revocation is immediate and needs no key material.

3. **Predicate discipline is the security-critical part.** Every statement that
   targets one kind filters on that kind's discriminator columns, and this is
   mirrored by tests, because the failure mode is silent and severe: a static-token
   rotation whose predicate omits `client_id IS NULL` also revokes every web session
   of that user, and an OAuth operation that omits `client_id = :client_id` can kill
   another client's or a static token's row. The rules as implemented:
   static-token operations always carry `client_id IS NULL` (+ `label`), OAuth
   operations always carry `client_id`, and `test_rbac.py::token_kind_isolation`
   asserts the isolation rather than trusting the review.

4. **Kinds have their own lifecycles on purpose.** Web sessions expire on a TTL;
   static tokens never expire (an operator revokes them, and rotating by `label`
   replaces the previous row atomically); OAuth access tokens live under the
   authorization server's TTLs and are killed by grant revocation and by refresh
   replay handling. `last_used_at` is written at most once per token per minute —
   enough for an operator to see a token is live, cheap enough for every request.

5. **Verification is kind-agnostic.** One `verify_bearer` resolves any of the three
   kinds to a viewer, which is why the MCP surface needs no token table of its own
   (ADR-0014) and why a password change or admin force-logout ends an agent's access
   with no MCP-specific code.

## Consequences

- Revoking "everything a person holds" is one `DELETE`/`UPDATE` over one table; the
  browser session, the agent's static token and any OAuth access tokens die together.
- Every request that authenticates costs a database round trip. Accepted: the
  alternative is a cache whose invalidation is the very problem revocation exists to
  solve.
- The static kind's "never expires" is a deliberate operational choice, so tokens
  carry a `label` for humans to rotate and revoke by; docs tell operators to prefer
  OAuth for long-lived agent access.

## Alternatives considered

- **JWTs with a signing key**: rejected — revocation becomes a denylist (i.e. a table
  anyway), key rotation and JWKS handling enter the picture for no gain at this
  scale, and the "stateless" benefit is not worth losing instant force-logout, which
  is a product feature here.
- **Three tables (one per kind)**: rejected — three revocation implementations, and
  force-logout becomes a cross-table transaction that a future kind would silently
  miss.
- **One table with a `kind` enum column**: rejected — the enum can disagree with the
  discriminator columns; deriving the kind from the columns means there is exactly
  one source of truth for what a row is, and predicates on those columns *are* the
  kind filter.
- **Storing a token's claims (roles, permissions) alongside it**: rejected — it makes
  revocation partial (the token row says one thing, `role_permissions` another).
