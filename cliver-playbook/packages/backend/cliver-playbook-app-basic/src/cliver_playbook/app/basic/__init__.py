"""basic: the foundations package — settings, runtime, and a demo API slice.

Public surface only; every name below is a plain import (no settings reads,
no engine, no app assembly — importing a package must never have side
effects; see ADR-0015 and ADR-0016).
"""

from cliver_playbook.app.basic.api.routes import ROUTERS
from cliver_playbook.app.basic.app import create_app
from cliver_playbook.app.basic.settings import Settings, get_settings, settings

__all__ = ["ROUTERS", "Settings", "create_app", "get_settings", "settings"]
