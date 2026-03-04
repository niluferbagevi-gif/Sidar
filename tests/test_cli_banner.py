import ast
from pathlib import Path


def _load_make_banner():
    source = Path("cli.py").read_text(encoding="utf-8")
    mod = ast.parse(source)
    target = next(
        node for node in mod.body if isinstance(node, ast.FunctionDef) and node.name == "_make_banner"
    )
    fn_module = ast.Module(body=[target], type_ignores=[])
    ast.fix_missing_locations(fn_module)
    ns = {}
    exec(compile(fn_module, filename="cli.py", mode="exec"), ns)
    return ns["_make_banner"]


def test_make_banner_handles_long_version_without_overflow():
    make_banner = _load_make_banner()
    banner = make_banner("2026.03.05-build-super-long-tag")
    lines = [line for line in banner.splitlines() if line]

    # Banner satırlarının genişliği tutarlı olmalı (çerçeve bozulmamalı)
    widths = {len(line) for line in lines}
    assert len(widths) == 1

    # Uzun sürüm metni kırpılmış olmalı ve satır sonu çerçevesi korunmalı
    version_line = next(line for line in lines if "Yazılım Mimarı & Baş Mühendis AI" in line)
    assert version_line.endswith("║")
    assert "…" in version_line
