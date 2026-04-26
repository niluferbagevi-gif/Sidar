from __future__ import annotations

import pytest

from core.dlp import get_dlp_engine

hypothesis = pytest.importorskip("hypothesis")
st = hypothesis.strategies


@hypothesis.given(st.text(min_size=1))
def test_dlp_never_crashes_on_arbitrary_input(text: str) -> None:
    masked, detections = get_dlp_engine().mask(text)
    assert isinstance(masked, str)
    assert isinstance(detections, list)
