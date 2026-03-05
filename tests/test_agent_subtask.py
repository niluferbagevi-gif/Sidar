import ast
from pathlib import Path


def _load_subtask_source() -> str:
    source = Path("agent/sidar_agent.py").read_text(encoding="utf-8")
    mod = ast.parse(source)
    cls = next(n for n in mod.body if isinstance(n, ast.ClassDef) and n.name == "SidarAgent")
    fn = next(n for n in cls.body if isinstance(n, ast.AsyncFunctionDef) and n.name == "_tool_subtask")
    return ast.get_source_segment(source, fn) or ""


def test_subtask_uses_configurable_max_steps_and_bounds():
    src = _load_subtask_source()
    assert 'getattr(self.cfg, "SUBTASK_MAX_STEPS", 5)' in src
    assert 'max(1, max_steps)' in src


def test_subtask_validates_toolcall_schema():
    src = _load_subtask_source()
    assert "ToolCall.model_validate(action)" in src
    assert "except ValidationError" in src


def test_get_config_avoids_stale_line_number_references():
    src = Path("agent/sidar_agent.py").read_text(encoding="utf-8")
    assert "[config.py satır" not in src