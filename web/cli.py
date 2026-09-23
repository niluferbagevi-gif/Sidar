"""Command-line entrypoint for the Sidar web server."""

from __future__ import annotations

import argparse
import asyncio
import inspect
import logging
from typing import Any

import uvicorn

from agent.sidar_agent import SidarAgent
from core.utils.network_validation import is_unspecified_bind, validate_bind_host

logger = logging.getLogger(__name__)


async def _prewarm_agent(agent: Any) -> None:
    """Validate agent start-up, then release loop-bound resources in the same loop.

    Process-wide caches (e.g. the embedding model) stay warm for the server's agent.
    """
    try:
        initialize = getattr(agent, "initialize", None)
        if callable(initialize):
            maybe_coro = initialize()
            if inspect.isawaitable(maybe_coro):
                await maybe_coro
    finally:
        db = getattr(getattr(agent, "memory", None), "db", None)
        close = getattr(db, "close", None)
        if callable(close):
            maybe_closed = close()
            if inspect.isawaitable(maybe_closed):
                await maybe_closed


def main() -> None:
    """Parse CLI flags, initialize the agent, and run the ASGI server."""
    import web_server

    cfg = web_server.cfg
    parser = argparse.ArgumentParser(description="Sidar Web Arayüzü")
    parser.add_argument(
        "--host", default=cfg.WEB_HOST, help=f"Sunucu adresi (varsayılan: {cfg.WEB_HOST})"
    )
    parser.add_argument(
        "--port", type=int, default=cfg.WEB_PORT, help=f"Port numarası (varsayılan: {cfg.WEB_PORT})"
    )
    parser.add_argument(
        "--level",
        choices=["restricted", "sandbox", "full"],
        help="Erişim seviyesi (varsayılan: .env'deki değer)",
    )
    parser.add_argument(
        "--provider",
        choices=["ollama", "gemini", "openai", "anthropic"],
        help="AI sağlayıcısı (varsayılan: .env'deki değer)",
    )
    parser.add_argument("--log", default="info", help="Log seviyesi (debug/info/warning)")
    args, _unknown_args = parser.parse_known_args()

    if args.level:
        cfg.ACCESS_LEVEL = args.level
    if args.provider:
        cfg.AI_PROVIDER = args.provider

    agent_version = ""
    try:
        prewarm_agent = SidarAgent(cfg)
        agent_version = str(getattr(prewarm_agent, "VERSION", "") or "")
        asyncio.run(_prewarm_agent(prewarm_agent))
    except Exception as exc:
        logger.warning(
            "Web server agent ön başlatması başarısız; sunucu yine de başlatılacak: %s", exc
        )
    # asyncio.run() above uses a throwaway event loop. Loop-bound resources such as
    # the asyncpg pool cannot be reused from uvicorn's loop, so the served agent is
    # always created lazily by web_server.get_agent() inside the server loop.
    web_server._agent = None

    try:
        validated_host = validate_bind_host(args.host)
    except ValueError as exc:
        logger.critical("Web sunucusu güvenlik politikasına takıldı: %s", exc)
        raise SystemExit(2) from exc
    args.host = validated_host
    display_host = "localhost" if is_unspecified_bind(validated_host) else validated_host
    version_label = f"v{agent_version}" if agent_version else f"v{getattr(cfg, 'VERSION', '?')}"

    print()
    print("  ╔══════════════════════════════════════╗")
    print("  ║  SİDAR Web Arayüzü                   ║")
    print(f"  ║  http://{display_host}:{args.port:<27}║")
    print("  ╚══════════════════════════════════════╝")
    print(f"     Sürüm: {version_label}")
    print()

    uvicorn.run(
        web_server.app,
        host=args.host,
        port=args.port,
        log_level=args.log.lower(),
    )


if __name__ == "__main__":
    main()
