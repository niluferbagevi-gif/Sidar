import pytest
from fastapi import HTTPException

from web.routes.memory_feedback import (
    EntityUpsertRequest,
    FeedbackRecordRequest,
    build_memory_feedback_router,
)


class _EntityMemory:
    def __init__(self):
        self.upserts = []
        self.deleted = True

    async def initialize(self):
        return None

    async def upsert(self, **kwargs):
        self.upserts.append(kwargs)

    async def get_profile(self, *, user_id):
        return {"user_id": user_id, "name": "Ada"}

    async def delete(self, *, user_id, key):
        return self.deleted and user_id == "u1" and key == "skill"


class _FeedbackStore:
    def __init__(self):
        self.records = []

    async def initialize(self):
        return None

    async def record(self, **kwargs):
        self.records.append(kwargs)

    async def stats(self):
        return {"count": len(self.records) or 1}


def _exports(*, entity_memory=None, feedback_store=None):
    router = build_memory_feedback_router(
        cfg=object(),
        entity_memory_cache={"instance": entity_memory},
        feedback_store_cache={"instance": feedback_store},
    )
    return router.legacy_exports


@pytest.mark.asyncio
async def test_memory_feedback_router_legacy_exports_success_paths():
    entity_memory = _EntityMemory()
    feedback_store = _FeedbackStore()
    exports = _exports(entity_memory=entity_memory, feedback_store=feedback_store)

    upsert = await exports["api_entity_upsert"](
        EntityUpsertRequest(user_id="u1", key="skill", value="python", ttl_days=7)
    )
    profile = await exports["api_entity_get_profile"]("u1")
    delete = await exports["api_entity_delete"]("u1", "skill")
    record = await exports["api_feedback_record"](
        FeedbackRecordRequest(user_id="u1", prompt="p", response="r", rating=5)
    )
    stats = await exports["api_feedback_stats"]()

    assert upsert.status_code == 200
    assert entity_memory.upserts == [{"user_id": "u1", "key": "skill", "value": "python", "ttl_days": 7}]
    assert b'"name":"Ada"' in profile.body
    assert b'"success":true' in delete.body
    assert record.status_code == 200
    assert feedback_store.records == [{"user_id": "u1", "prompt": "p", "response": "r", "rating": 5, "note": ""}]
    assert b'"count":1' in stats.body


@pytest.mark.asyncio
async def test_memory_feedback_router_entity_memory_factory_failure(monkeypatch):
    def _raise_factory(_cfg):
        raise RuntimeError("entity unavailable")

    import core.entity_memory as entity_memory_module

    monkeypatch.setattr(entity_memory_module, "get_entity_memory", _raise_factory)
    exports = _exports(entity_memory=None)

    with pytest.raises(HTTPException) as exc_info:
        await exports["api_entity_get_profile"]("u1")

    assert exc_info.value.status_code == 501
    assert "EntityMemory başlatılamadı" in exc_info.value.detail


@pytest.mark.asyncio
async def test_memory_feedback_router_feedback_store_factory_failure(monkeypatch):
    def _raise_factory(_cfg):
        raise RuntimeError("feedback unavailable")

    import core.active_learning as active_learning_module

    monkeypatch.setattr(active_learning_module, "get_feedback_store", _raise_factory)
    exports = _exports(feedback_store=None)

    with pytest.raises(HTTPException) as exc_info:
        await exports["api_feedback_stats"]()

    assert exc_info.value.status_code == 501
    assert "FeedbackStore başlatılamadı" in exc_info.value.detail
