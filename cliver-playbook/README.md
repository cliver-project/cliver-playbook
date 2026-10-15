# cliver-playbook

A personal engineering asset library for a one-person company: copy-based project
templates plus Claude Code skills that assemble them into new services. Code lives in
this git repository; skills read from it at project-creation time (ADR-0007).

## What's inside

| Template          | What you get                                                                  |
|-------------------|-------------------------------------------------------------------------------|
| `service-scaffold` | Full-stack starter: FastAPI + async SQLAlchemy + PostgreSQL, React 19 + Vite + Tailwind v4 + shadcn/ui, i18n (en/zh), light/dark theming, migrations, tests |
| `user-management`  | Complete RBAC (users / roles / permissions), password login with lockout + must-change-password, generic OIDC login, OAuth 2.1 provider for AI-agent clients, admin UI, unified audit log |
| `mcp-server`       | MCP server (official SDK, streamable-http) mounted into the app: token gate, OAuth handshake, example tools with permission enforcement, tool-call audit |

Every template is a **complete runnable application** on its own — clone, `make init`,
`make backend-test`, green. Integration into a scaffold-based project is a documented
copy manifest (`INTEGRATION.md` in each template).

## Skills

Install once (symlink or copy into `~/.claude/skills/`):

```bash
for s in cliver-playbook/skills/*/; do ln -s "$(pwd)/$s" ~/.claude/skills/"$(basename "$s")"; done
```

- **new-cliver-service** — bootstrap a new project from `service-scaffold` (rename,
  db, migrations, tests, git init)
- **add-user-management** — layer RBAC + auth onto a scaffold project
- **add-mcp-server** — layer the MCP server onto a project that has user-management

Skills resolve this repository via `CLIVER_PLAYBOOK_ROOT` (default:
`~/sources/cliver-project/mcp_x/cliver-playbook`).

## Architecture decisions

`adr/` holds the "why" behind every structural choice — read before deviating:

- 0001 PostgreSQL-only + async SQLAlchemy; dual driver URLs
- 0002 Fixed `app` package; three-token rename surface
- 0003 RBAC tables + code-defined permission catalog
- 0004 One `auth_tokens` table, three token kinds
- 0005 OAuth 2.1 provider ownership (identity domain)
- 0006 MCP sub-app mounting + lifespan composition
- 0007 Copy-merge template model + Alembic chaining
- 0008 Frontend platform: Vite (not Next), i18n, theming, axios + TanStack Query

## Maintenance

- `python scripts/check_drift.py` — verifies shared files inside user-management/
  mcp-server/ haven't drifted from service-scaffold beyond the declared supersets.
- Everything is English-only and domain-neutral (ADR writing rule: no client names,
  no real URLs, no credentials ever enter this repository).
