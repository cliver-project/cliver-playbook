"""FastAPI application assembly.

Routers are included explicitly — a later template adds its routers to this
file (shipped as a superset), keeping assembly visible in one place.
"""

import logging

from fastapi import FastAPI

from app.api import items, meta
from app.core.config import settings

logging.basicConfig(level=settings.log_level.upper())
logger = logging.getLogger("cliver_app")

app = FastAPI(title=settings.app_name, version="0.1.0")

app.include_router(meta.router)
app.include_router(items.router)

logger.info("Application assembled: %s (API prefix %s)", settings.app_name, settings.api_v1_prefix)
