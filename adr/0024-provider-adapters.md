# ADR-0024: Provider adapters for non-OAuth2 identity providers

**Status:** Accepted (2026-11-06).
**Context:** ADR-0005 keeps the app a plain OIDC client and makes providers
configuration, not code. That holds for standards-shaped IdPs, but two common
providers are not OAuth2-shaped: WeChat Open Platform is QR-connect with plain
GET calls and `errcode`-in-200 failures, and Alipay is an RSA2-signed form
gateway with no token or userinfo endpoints. The project-side workaround was
to point all three provider URLs back at the same process and translate the
protocols behind a loopback HTTP hop. That works, but it makes the app POST the
`client_secret` — for Alipay, the application private key — to a URL it
controls, carries the upstream token between two HTTP requests in an
application-level envelope, and leaves deployments depending on loopback
isolation plus documentation.

## Decision

1. **Adapters are a registry, selected by configuration.** A provider entry may
   set `adapter: <name>`; an empty value keeps the standard OAuth2/OIDC flow.
   When set, the adapter owns the authorize URL and the entire
   code-for-identity exchange. Provider selection stays a configuration change:
   enabling WeChat or Alipay requires no application code.
2. **One identity contract.** Adapters return `Identity(subject, claims)`.
   `subject` is the provider-stable identifier (WeChat `openid`, Alipay
   `user_id`); claims use normalized keys (`name`, `picture`, `email`,
   `phone_number`) with raw provider fields preserved. The standard path wraps
   its userinfo payload in the same contract, so account lookup, provisioning
   and linking depend on one shape rather than each provider's JSON.
3. **Built-ins ship in the identity package, with an optional dependency.**
   `wechat` and `alipay` are registered at import time. Alipay's RSA signing
   uses `cryptography`, declared as the `alipay` extra and imported lazily, so
   deployments that do not enable Alipay do not install or load it. Projects
   register private adapters with `register_adapter` before the first request;
   the registry rejects duplicate names and unknown selections at startup, not
   at first login.
4. **Credentials and upstream tokens do not cross a playbook HTTP endpoint.**
   The adapter performs both upstream calls in-process, so the upstream access
   token never leaves the adapter and no AES envelope is needed. Alipay's
   private key signs requests locally and is never transmitted. WeChat's app
   secret still travels to WeChat in a query string because that is its
   protocol; the adapter therefore pins httpx's logger below INFO process-wide
   (its request log prints full URLs), and error messages name only the step
   and numeric provider code.
5. **PKCE is a standard-flow feature, not an adapter requirement.** WeChat and
   Alipay do not support it for these flows; the adapter contract still passes
   the challenge through for private adapters that can use it.
6. **Alipay response signatures are not verified in P0.** The gateway response
   is trusted over TLS. Response-signature verification is a follow-up once a
   public-key setting exists; this is recorded as a known limitation rather
   than silently assumed.
7. **The state cookie, callback routes and account-linking semantics are
   unchanged.** Adapters change only how the authorize URL is built and how the
   code becomes an `Identity`; login, linking and auditing stay in one place.

## Consequences

- A project can delete its loopback translator, its self-referential provider
  URLs, and the token envelope; the provider configuration names an adapter.
- Adapter-backed providers still require `client_id` and `client_secret`; the
  settings validator only drops the discovery/explicit-endpoint requirement.
- The callback URL still carries `code` and `state`, so removing loopback
  self-calls does not by itself justify disabling access logs; keep the
  usual callback/log hygiene.
- Project adapters must be registered during application assembly, before the
  first request; in a multi-worker deployment every worker runs that same
  registration code.
- Adding a provider whose protocol no one has implemented remains a code
  change: a new adapter. That is the deliberate boundary — generic template
  configuration cannot express RSA-signed gateways.

## Alternatives considered

- **Per-provider branches inside `oidc.py`**: rejected — it multiplies the flow
  by provider count and makes every new non-standard provider a change to the
  core flow.
- **A protocol setting with special cases for WeChat/Alipay**: rejected — it
  is the same coupling with a narrower name.
- **Generic endpoint templates**: rejected — WeChat needs two GETs with
  provider-specific error handling, and Alipay needs request signing; neither
  fits URL-plus-form configuration.
- **Keeping the loopback workaround**: rejected — it sends the private key to
  an HTTP endpoint in the same process and requires an application envelope
  for the upstream token, which is more moving parts than an adapter.

## Amendment to ADR-0005

Point 5 ("Providers are configuration, not code") gains a third provider shape:
in addition to discovery-based and explicit-endpoint providers, an entry may
select a registered protocol adapter. The rest of ADR-0005 is unchanged.
