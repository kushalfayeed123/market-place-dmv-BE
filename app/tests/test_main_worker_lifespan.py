"""Tests that the notification worker is started/stopped with the app lifespan."""

import asyncio
from unittest.mock import AsyncMock

import app.main as main_module
from app.main import app, shutdown_event, startup_event


async def test_startup_starts_notification_worker_and_shutdown_stops_it(monkeypatch):
    monkeypatch.setattr(main_module, "init_redis", AsyncMock())
    monkeypatch.setattr(
        "app.core.storage.key_exists", lambda **kwargs: False, raising=False
    )

    started = asyncio.Event()
    stopped = False

    async def fake_start():
        started.set()
        # Simulate the worker loop: runs until cancelled/stopped.
        await asyncio.Event().wait()

    def fake_stop():
        nonlocal stopped
        stopped = True

    monkeypatch.setattr(
        "app.workers.notification_worker.start_notification_worker", fake_start
    )
    monkeypatch.setattr(
        "app.workers.notification_worker.stop_notification_worker", fake_stop
    )

    await startup_event()
    task = getattr(app.state, "notification_worker_task", None)
    assert task is not None
    assert await asyncio.wait_for(started.wait(), timeout=5)
    assert not task.done()

    await shutdown_event()
    assert stopped is True
    assert task.done()
