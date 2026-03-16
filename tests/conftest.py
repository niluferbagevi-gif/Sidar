import asyncio

import pytest


@pytest.fixture(scope="session")
def event_loop():
    """Tüm test session'ı için tek bir event loop garantisi (DB testleri için şarttır)."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()