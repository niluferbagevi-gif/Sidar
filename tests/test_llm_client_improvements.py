import ast
from pathlib import Path


def test_ollama_stream_parses_trailing_buffer():
    src = Path("core/llm_client.py").read_text(encoding="utf-8")
    assert "if buffer.strip():" in src
    assert "body = json.loads(buffer)" in src


def test_gemini_stream_uses_safe_chunk_text_access():
    src = Path("core/llm_client.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "GeminiClient")
    fn = next(n for n in cls.body if isinstance(n, ast.AsyncFunctionDef) and n.name == "_stream_gemini_generator")
    fn_src = ast.get_source_segment(src, fn) or ""

    assert 'getattr(chunk, "text", "")' in fn_src
    assert "yield text" in fn_src


def test_llm_client_has_factory_and_provider_guards():
    src = Path("core/llm_client.py").read_text(encoding="utf-8")
    assert "class BaseLLMClient(ABC)" in src
    assert "class OllamaClient(BaseLLMClient)" in src
    assert "class GeminiClient(BaseLLMClient)" in src
    assert "class OpenAIClient(BaseLLMClient)" in src
    assert "class LLMClient:" in src
    assert 'elif self.provider == "openai"' in src


def test_llm_client_keeps_timeout_and_gemini_safety_guards():
    src = Path("core/llm_client.py").read_text(encoding="utf-8")
    assert "def _build_ollama_timeout" in src
    assert "httpx.Timeout(timeout_seconds, connect=10.0)" in src
    assert "response_mime_type" in src
    assert "safety_settings=safety_settings" in src
    assert "HARM_CATEGORY_DANGEROUS_CONTENT" in src
    assert "_ensure_json_text(text, \"Gemini\") if json_mode else text" in src