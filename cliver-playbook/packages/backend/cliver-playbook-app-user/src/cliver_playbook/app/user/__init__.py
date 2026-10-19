"""user: the identity package — accounts, RBAC, OIDC login, OAuth 2.1 provider.

Builds on ``basic`` (settings, runtime, database access) and contributes the
authentication/authorization surface of a cliver-playbook application.

Public surface only; every name below is a plain import (no settings reads,
no engine, no app assembly — importing a package must never have side
effects; see ADR-0015 and ADR-0016).
"""

# Load-bearing import: registering the identity settings section before any
# module that reads the settings registry (ADR-0021).
from cliver_playbook.app.user import settings_section  # noqa: F401
from cliver_playbook.app.user.api.routes import ROUTERS
from cliver_playbook.app.user.app import create_app
from cliver_playbook.app.user.settings import Settings, get_settings, settings

__all__ = ["ROUTERS", "Settings", "create_app", "get_settings", "settings"]
