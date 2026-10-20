---
name: assemble-project
description: Assemble a new one-person project from cliver-playbook packages, preferring composition and recording any vendored code.
---

# Assemble a project from cliver-playbook

Run every command from the cliver-playbook checkout. The target project is a
separate directory; never assemble by editing the playbook packages.

## Procedure

1. Read `REUSE.md` and
   `skills/assemble-project/assets/project-manifest.example.yaml`.
2. Choose a profile and mode with the user. Default to `compose`; use `vendor`
   only when the user names a customization the package cannot express.
   - `minimal` — basic
   - `web` — basic + user
   - `rag` — basic + user + rag
   - `mcp` — basic + user + rag + mcp
3. Run the planner and confirm its output before touching the target:
   ```sh
   uv run python scripts/assemble_project.py \
     --profile <profile> --mode <mode> --target <dir> --dry-run
   ```
4. Create the target skeleton and wire the selected packages following the
   playbook README and ADRs: workspace manifests, backend routers via
   `include_router` (never `FastAPI.mount()`), settings layers, and the
   migration chains in dependency order.
5. For `vendor`, use `scripts/vendor_package.py`, repeating `--package` for
   every package copied into the shared `vendor/cliver_playbook` tree. The
   script writes one `vendor/FORKED_FROM.md` section per package; confirm each
   import resolves under `vendor/`. Preserve the `cliver_playbook` namespace;
   never rename packages by hand. If `scripts/vendor_package.py` is absent,
   stop and report that vendor mode is not implemented.
6. Write `project-manifest.yaml` from the example and validate it:
   ```sh
   uv run python scripts/validate_project_manifest.py project-manifest.yaml
   ```
7. Run the project's lint, tests, and frontend build, then boot it and hit
   `/api/v1/health`. Stop and report on any failure; do not paper over it.
8. Never modify the playbook's package sources while assembling a project. If
   the project needs an infrastructure change, contribute it to the playbook
   in a separate change.
