from cliver_playbook.app.basic import runtime, runtime_settings


async def test_lifespan_disposes_runtime(monkeypatch):
    called = False

    async def fake_dispose() -> None:
        nonlocal called
        called = True

    async def fake_load() -> None:
        return None

    monkeypatch.setattr(runtime_settings, "load_persisted_settings", fake_load)
    monkeypatch.setattr(runtime, "dispose", fake_dispose)
    async with runtime_settings.settings_lifespan(None):
        pass
    assert called is True
