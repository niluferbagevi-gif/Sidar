from __future__ import annotations

import factory


class MemoryRecordFactory(factory.DictFactory):
    """Lightweight shared factory for memory-like records used in tests."""

    id = factory.Sequence(lambda n: n + 1)
    user_id = "test-user"
    content = factory.Faker("sentence")
    source = "unit-test"
