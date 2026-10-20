from contextlib import asynccontextmanager

from cliver_playbook.app.basic import runtime, runtime_settings
from cliver_playbook.app.mcp import app as mcp_app


class _Manager:
    @asynccontextmanager
    async def run(self):
        yield


async def test_composed_lifespan_disposes_the_engine(monkeypatch):
    disposed = False

    async def fake_load() -> None:
        return None

    async def fake_dispose() -> None:
        nonlocal disposed
        disposed = True

    monkeypatch.setattr(runtime_settings, "load_persisted_settings", fake_load)
    monkeypatch.setattr(runtime, "dispose", fake_dispose)
    monkeypatch.setattr(mcp_app, "install_streamable_app", lambda: _Manager())

    async with mcp_app._lifespan(None):
        assert disposed is False
    assert disposed is True
