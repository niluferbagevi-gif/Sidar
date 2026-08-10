"""Single-request JSON RPC worker for the isolated plugin container."""

from __future__ import annotations

import json
import sys

# Reserve the process's real stdout exclusively for the one JSON RPC response
# main() writes at the very end. Anything else that writes to sys.stdout
# during import or request handling would land *before* that JSON and break
# json.loads() on the host side (web/plugins/sandbox.py's request()) --
# discovered via SEC-PLUGIN-001's real-container integration test: config.py's
# root logging handler targets stdout by default (console visibility for the
# normal launcher use case) and fires a warning whenever this worker's
# --read-only container filesystem blocks its log-file handler, which
# corrupted the RPC channel with a log line before the response. Swap
# sys.stdout to stderr immediately, before any import that might log (the
# host never reads the subprocess's stderr, so nothing here is relayed), and
# keep the untouched original stream aside for main() to write the response
# on -- this also protects against a future/plugin-side stray print().
_RPC_STDOUT = sys.stdout
sys.stdout = sys.stderr

import asyncio  # noqa: E402
import inspect  # noqa: E402
from typing import Any, cast  # noqa: E402

from agent.base_agent import BaseAgent  # noqa: E402
from web.plugins.sandbox import PLUGIN_RPC_VERSION, run_plugin_source_in_process  # noqa: E402


def _agent_class(namespace: dict[str, Any], requested: str | None) -> type[BaseAgent]:
    candidates = [
        value
        for value in namespace.values()
        if inspect.isclass(value) and value is not BaseAgent and issubclass(value, BaseAgent)
    ]
    if requested:
        selected = namespace.get(requested)
        if selected not in candidates:
            raise ValueError(f"Belirtilen BaseAgent sınıfı bulunamadı: {requested}")
        return cast(type[BaseAgent], selected)
    if not candidates:
        raise ValueError("Plugin içinde BaseAgent türevi bir sınıf bulunamadı")
    return candidates[0]


def handle_request(request: dict[str, Any]) -> dict[str, Any]:
    """Validate an RPC envelope and execute its one allowed operation."""
    if request.get("rpc_version") != PLUGIN_RPC_VERSION:
        raise ValueError("Uyumsuz plugin RPC sürümü")
    action = request.get("action")
    if action not in {"describe", "run_task"}:
        raise ValueError("Desteklenmeyen plugin RPC işlemi")
    source = request.get("source")
    if not isinstance(source, str):
        raise ValueError("Plugin kaynağı metin olmalıdır")
    namespace = run_plugin_source_in_process(source, str(request.get("module_label") or "plugin"))
    cls = _agent_class(namespace, request.get("class_name"))
    response: dict[str, Any] = {
        "rpc_version": PLUGIN_RPC_VERSION,
        "ok": True,
        "class_name": cls.__name__,
        "description": (cls.__doc__ or "").strip().split("\n")[0],
    }
    if action == "run_task":
        prompt = request.get("task_prompt")
        if not isinstance(prompt, str):
            raise ValueError("Plugin görev girdisi metin olmalıdır")
        result = asyncio.run(cls().run_task(prompt))
        if not isinstance(result, str):
            raise ValueError("Plugin görev çıktısı metin olmalıdır")
        response["result"] = result
    return response


def main() -> int:
    """Read one envelope from stdin and emit one redacted response."""
    try:
        request = json.load(sys.stdin)
        if not isinstance(request, dict):
            raise ValueError("Plugin RPC zarfı nesne olmalıdır")
        response = handle_request(request)
    except Exception as exc:  # Worker boundary must serialize all failures.
        response = {"rpc_version": PLUGIN_RPC_VERSION, "ok": False, "error": str(exc)[:500]}
    json.dump(response, _RPC_STDOUT, ensure_ascii=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
