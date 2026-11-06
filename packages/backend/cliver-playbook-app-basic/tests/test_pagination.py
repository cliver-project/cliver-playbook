"""Shared pagination contract: the Page envelope and the query dependency.

The envelope is transport-agnostic; the dependency only parses and validates
limit/offset. Endpoints that page a query use both together, so the response
shape and the accepted window never drift between packages.
"""

import httpx
import pytest
from fastapi import Depends, FastAPI
from pydantic import ValidationError

from cliver_playbook.app.basic.api.pagination import PageParams, page_params
from cliver_playbook.app.basic.schemas.pagination import Page


def _app(**options) -> FastAPI:
    app = FastAPI()
    dependency = page_params(**options)

    @app.get("/page")
    async def route(params: PageParams = Depends(dependency)) -> dict:
        return {"limit": params.limit, "offset": params.offset}

    return app


async def _get(app: FastAPI, path: str) -> httpx.Response:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.get(path)


async def test_page_carries_items_total_and_window():
    page = Page[int](items=[1, 2], total=5, limit=2, offset=2)
    assert page.model_dump() == {
        "items": [1, 2],
        "total": 5,
        "limit": 2,
        "offset": 2,
    }


def test_page_rejects_impossible_bookkeeping():
    with pytest.raises(ValidationError):
        Page[int](items=[], total=-1, limit=10, offset=0)
    with pytest.raises(ValidationError):
        Page[int](items=[], total=0, limit=0, offset=0)
    with pytest.raises(ValidationError):
        Page[int](items=[], total=0, limit=10, offset=-1)


async def test_page_params_defaults_and_overrides():
    app = _app(default_limit=20, max_limit=50)
    assert (await _get(app, "/page")).json() == {"limit": 20, "offset": 0}
    assert (await _get(app, "/page?limit=5&offset=10")).json() == {"limit": 5, "offset": 10}


async def test_page_params_rejects_out_of_range_values():
    app = _app(default_limit=20, max_limit=50)
    for path in ("/page?limit=0", "/page?limit=51", "/page?offset=-1"):
        assert (await _get(app, path)).status_code == 422


def test_page_params_factory_validates_its_bounds():
    with pytest.raises(ValueError):
        page_params(default_limit=0)
    with pytest.raises(ValueError):
        page_params(default_limit=51, max_limit=50)
