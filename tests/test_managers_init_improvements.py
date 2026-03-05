from pathlib import Path


def test_managers_init_uses_single_export_source_for_all():
    src = Path("managers/__init__.py").read_text(encoding="utf-8")
    assert "_EXPORTED_MANAGERS = (" in src
    assert "__all__ = [cls.__name__ for cls in _EXPORTED_MANAGERS]" in src
    assert "TodoManager" in src
