import os
import sys
import asyncio

import pytest


PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


@pytest.fixture(scope="session")
def event_loop():
    """Tüm test session'ı için tek bir event loop garantisi (DB testleri için şarttır)."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()
