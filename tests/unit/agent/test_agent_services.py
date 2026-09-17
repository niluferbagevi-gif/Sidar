"""Unit tests for focused services behind the SidarAgent facade."""

import pytest

from agent.services.response_service import parse_tool_call
from agent.services.tool_service import execute_tool


def test_response_service_normalizes_json_markdown_and_fallbacks() -> None:
    assert parse_tool_call('```json\n{"argument":"done"}\n```') == {
        "tool": "final_answer",
        "argument": "done",
    }
    assert parse_tool_call("not-json") == {
        "tool": "final_answer",
        "argument": "not-json",
    }


@pytest.mark.asyncio
async def test_tool_service_supports_sync_and_async_handlers() -> None:
    async def async_handler(argument: str) -> str:
        return f"async:{argument}"

    handlers = {
        "_tool_sync": lambda argument: f"sync:{argument}",
        "_tool_async": async_handler,
    }
    resolve = handlers.get

    assert await execute_tool(" SYNC ", "one", resolve_handler=resolve) == "sync:one"
    assert await execute_tool("async", "two", resolve_handler=resolve) == "async:two"


@pytest.mark.asyncio
async def test_tool_service_rejects_invalid_handlers() -> None:
    with pytest.raises(ValueError, match="Araç adı boş"):
        await execute_tool("", "x", resolve_handler=lambda _name: None)
    with pytest.raises(ValueError, match="Bilinmeyen araç"):
        await execute_tool("missing", "x", resolve_handler=lambda _name: None)
    with pytest.raises(TypeError, match="çağrılabilir değil"):
        await execute_tool("broken", "x", resolve_handler=lambda _name: "not callable")
