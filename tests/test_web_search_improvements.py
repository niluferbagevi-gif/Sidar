from pathlib import Path


def test_search_uses_structured_no_result_marker_instead_of_hata_string_matching():
    src = Path("managers/web_search.py").read_text(encoding="utf-8")
    assert "_NO_RESULTS_PREFIX = \"[NO_RESULTS]\"" in src
    assert "def _is_actionable_result" in src
    assert "def _normalize_result_text" in src
    assert '"[HATA]" not in res' not in src


def test_search_result_count_is_safely_clamped():
    src = Path("managers/web_search.py").read_text(encoding="utf-8")
    assert "except (TypeError, ValueError):" in src
    assert "n = max(1, min(n, 10))" in src


def test_fetch_scrape_pipeline_uses_async_client_utf8_and_context_limit():
    src = Path("managers/web_search.py").read_text(encoding="utf-8")
    assert "async def scrape_url(self, url: str) -> str:" in src
    assert "async with httpx.AsyncClient(" in src
    assert "resp.encoding = \"utf-8\"" in src
    assert "def _truncate_content(self, text: str) -> str:" in src
    assert "... [İçerik çok uzun olduğu için kesildi]" in src


def test_web_search_uses_browser_like_headers_and_bs4_cleanup():
    src = Path("managers/web_search.py").read_text(encoding="utf-8")
    assert "from bs4 import BeautifulSoup" in src
    assert "Chrome/119.0.0.0 Safari/537.36" in src
    assert "for tag in soup([\"script\", \"style\", \"nav\", \"footer\", \"header\"]):" in src


def test_web_search_config_supports_scrape_limit_alias():
    src = Path("config.py").read_text(encoding="utf-8")
    assert "WEB_SCRAPE_MAX_CHARS" in src
    assert "WEB_FETCH_MAX_CHARS" in src

def test_web_search_avoids_runtime_sidar_agent_import_to_prevent_circular_dependency():
    src = Path("managers/web_search.py").read_text(encoding="utf-8")
    assert "TYPE_CHECKING" in src
    assert "if TYPE_CHECKING:" in src
    assert "from agent.sidar_agent import SidarAgent" in src
