import ast
from pathlib import Path


def test_ollama_stream_parses_trailing_buffer():
    src = Path("core/llm_client.py").read_text(encoding="utf-8")
    assert "if buffer.strip():" in src
    assert "body = json.loads(buffer)" in src


def test_gemini_stream_uses_safe_chunk_text_access():
    src = Path("core/llm_client.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "LLMClient")
    fn = next(n for n in cls.body if isinstance(n, ast.AsyncFunctionDef) and n.name == "_stream_gemini_generator")
    fn_src = ast.get_source_segment(src, fn) or ""

    assert 'getattr(chunk, "text", "")' in fn_src
    assert "yield text" in fn_src