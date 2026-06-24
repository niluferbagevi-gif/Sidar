import importlib
import logging
from types import SimpleNamespace

import pytest

from core.db import prompt_registry


@pytest.mark.asyncio
async def test_ensure_default_prompt_registry_logs_upsert_failure(monkeypatch, caplog):
    class Loader:
        def exec_module(self, module):
            module.SIDAR_SYSTEM_PROMPT = "default prompt"

    monkeypatch.setattr(
        importlib.util,
        "spec_from_file_location",
        lambda *_args, **_kwargs: SimpleNamespace(loader=Loader()),
    )
    monkeypatch.setattr(importlib.util, "module_from_spec", lambda _spec: SimpleNamespace())

    async def no_active_prompt(*_args, **_kwargs):
        return None

    monkeypatch.setattr(prompt_registry, "get_active_prompt", no_active_prompt)

    async def raise_upsert(*_args, **_kwargs):
        raise RuntimeError("db down")

    monkeypatch.setattr(prompt_registry, "upsert_prompt", raise_upsert)

    with caplog.at_level(logging.WARNING, logger=prompt_registry.logger.name):
        await prompt_registry.ensure_default_prompt_registry(
            SimpleNamespace(), prompt_record_cls=SimpleNamespace
        )

    assert "Varsayılan prompt kaydı oluşturulamadı: db down" in caplog.text
