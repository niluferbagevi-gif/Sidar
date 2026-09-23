"""Provider preflight checks for the launcher (API keys, Ollama reachability).

Extracted from ``main.preflight``; messages are unchanged.
"""

from __future__ import annotations

import logging
from typing import Any

# Terminal renkleri (ANSI). main.py'nin kendi sabitleriyle birebir aynı.
_GREEN = "\033[92m"
_YELLOW = "\033[93m"
_RED = "\033[91m"
_RESET = "\033[0m"

PROVIDER_API_KEY_SETTINGS: dict[str, str] = {
    "gemini": "GEMINI_API_KEY",
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
}


def warn_missing_provider_api_key(provider: str, cfg: Any, *, logger_obj: logging.Logger) -> None:
    """Bulut sağlayıcı seçildiyse ve API anahtarı boşsa uyarı yazar."""
    key_name = PROVIDER_API_KEY_SETTINGS.get(provider)
    if key_name is None or getattr(cfg, key_name, None):
        return
    message = f"Uyarı: {key_name} boş görünüyor. API çağrıları başarısız olabilir."
    logger_obj.warning(message)
    print(f"{_RED}⚠ {message}{_RESET}")


def check_ollama_reachability(cfg: Any, *, logger_obj: logging.Logger) -> None:
    """Ollama ``/api/tags`` uç noktasına kısa zaman aşımıyla erişimi doğrular."""
    try:
        import httpx

        httpx_http_error: type[BaseException] = getattr(httpx, "HTTPError", RuntimeError)
        base = getattr(cfg, "OLLAMA_URL", "http://localhost:11434").rstrip("/")
        tags_url = base + "/tags" if base.endswith("/api") else base + "/api/tags"
        with httpx.Client(timeout=2) as client:
            code = client.get(tags_url).status_code
        if code == 200:
            print(f"{_GREEN}✅ Ollama erişimi başarılı ({base}).{_RESET}")
        else:
            logger_obj.warning("Ollama health kontrolü beklenmeyen durum kodu döndürdü: %s", code)
            print(f"{_YELLOW}⚠ Ollama yanıt kodu: {code}{_RESET}")
    except ImportError:
        logger_obj.warning("'httpx' kütüphanesi kurulu değil, Ollama ağ kontrolü atlandı.")
        print(f"{_YELLOW}⚠ 'httpx' kütüphanesi kurulu değil, Ollama ağ kontrolü atlandı.{_RESET}")
    except (httpx_http_error, RuntimeError, OSError) as exc:
        logger_obj.warning("Ollama erişimi doğrulanamadı: %s", exc)
        print(
            f"{_RED}⚠ Ollama erişimi doğrulanamadı. Servisin (Ollama) çalıştığından emin "
            f"olun.{_RESET}"
        )
