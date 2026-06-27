"""Command-line entrypoint for the Sidar web server."""

from __future__ import annotations

import argparse
import asyncio
import inspect
import logging

import uvicorn

from agent.sidar_agent import SidarAgent
from core.utils.network_validation import is_unspecified_bind, validate_bind_host

logger = logging.getLogger(__name__)


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

    try:
        web_server._agent = SidarAgent(cfg)
        initialize_result = getattr(web_server._agent, "initialize", None)
        if callable(initialize_result):
            maybe_coro = initialize_result()
            if inspect.iscoroutine(maybe_coro):
                asyncio.run(maybe_coro)
    except Exception as exc:
        logger.warning(
            "Web server agent ön başlatması başarısız; sunucu yine de başlatılacak: %s", exc
        )
        web_server._agent = None

    try:
        validated_host = validate_bind_host(args.host)
    except ValueError as exc:
        logger.critical("Web sunucusu güvenlik politikasına takıldı: %s", exc)
        raise SystemExit(2) from exc
    args.host = validated_host
    display_host = "localhost" if is_unspecified_bind(validated_host) else validated_host
    agent_version = getattr(web_server._agent, "VERSION", "") if web_server._agent is not None else ""
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
