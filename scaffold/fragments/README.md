# Scaffold fragments

Each selected module may contribute a fragment at
`scaffold/fragments/<module-id>/files/`. The apply step renders every file in
that directory into the new project:

- a file ending in `.j2` is rendered with Jinja2 and written without the suffix;
- every other file is copied byte for byte;
- a template that renders to nothing is skipped (this is how feature-specific
  files and CI workflows disappear when their module is disabled).

The render context is documented in `scripts/scaffold_project.py`
(`_template_context`): `project`, `project_title`, `playbook`, `manifest`,
`modules`, `ui`, `api`, `model`, `agent`, `contracts`, `ci`, `release`,
`mobile_features`, `mobile_layouts`, `reference_slices`, `warnings`, and the
`enabled(module_id)` helper.

Rules:

- A fragment owns only its module's files. Never write another module's path.
- Two fragments writing the same path with different content is an error.
- No deployment-specific hosts, credentials or endpoints in fragments.
- Reference slices (for example products) are examples, not infrastructure;
  they are clearly marked and the project owns and may delete them.
