from pathlib import Path


def test_web_ui_sanitizes_marked_output_before_innerhtml():
    src = Path("web_ui/index.html").read_text(encoding="utf-8")
    assert "function sanitizeRenderedHtml(html)" in src
    assert "blockedTags = new Set(['script', 'iframe', 'object', 'embed', 'form', 'meta', 'link'])" in src
    assert "name.startsWith('on')" in src
    assert "value.startsWith('javascript:')" in src
    assert "sanitizeRenderedHtml(marked.parse(rawText" in src