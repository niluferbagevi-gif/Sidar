"""Create local, git-ignored Sidar environment files from tracked templates."""

from __future__ import annotations

import argparse
import json
import secrets
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PROFILE = "development"
SECRET_PLACEHOLDERS = {
    "POSTGRES_PASSWORD": ("replace-with-a-strong-24-plus-character-password", "__GENERATE__"),
    "API_KEY": ("replace-with-a-local-development-api-key",),
    "JWT_SECRET_KEY": ("replace-with-a-local-development-jwt-secret-32-plus-chars",),
}


def _profile_paths(profile: str, *, project_root: Path = PROJECT_ROOT) -> tuple[Path, Path]:
    normalized = str(profile or DEFAULT_PROFILE).strip().lower()
    if not normalized or any(part in normalized for part in ("/", "\\", "..")):
        raise ValueError(f"Geçersiz SIDAR_ENV profili: {profile!r}")
    return project_root / f".env.{normalized}.example", project_root / f".env.{normalized}"


def _replace_assignment(text: str, key: str, value: str) -> str:
    prefix = f"{key}="
    lines = []
    replaced = False
    for line in text.splitlines():
        if line.startswith(prefix):
            lines.append(f"{prefix}{value}")
            replaced = True
        else:
            lines.append(line)
    if not replaced:
        lines.append(f"{prefix}{value}")
    return "\n".join(lines) + "\n"


def render_env_template(
    template: str,
    *,
    profile: str = DEFAULT_PROFILE,
    generate_secrets: bool = True,
) -> tuple[str, dict[str, bool]]:
    """Render a template, pin SIDAR_ENV, and optionally replace local placeholder secrets."""
    rendered = _replace_assignment(template, "SIDAR_ENV", profile)
    generated: dict[str, bool] = {}
    if not generate_secrets:
        return rendered if rendered.endswith("\n") else rendered + "\n", generated

    for key, placeholders in SECRET_PLACEHOLDERS.items():
        if not any(f"{key}={placeholder}" in rendered for placeholder in placeholders):
            generated[key] = False
            continue
        rendered = _replace_assignment(rendered, key, secrets.token_urlsafe(32))
        generated[key] = True
    return rendered if rendered.endswith("\n") else rendered + "\n", generated


def bootstrap_profile_env(
    profile: str = DEFAULT_PROFILE,
    *,
    project_root: Path = PROJECT_ROOT,
    force: bool = False,
    generate_secrets: bool = True,
) -> dict[str, Any]:
    """Copy .env.<profile>.example to .env.<profile> with safe local defaults."""
    source, target = _profile_paths(profile, project_root=project_root)
    if not source.is_file():
        raise FileNotFoundError(f"Ortam şablonu bulunamadı: {source}")
    if target.exists() and not force:
        return {
            "profile": profile,
            "created": False,
            "reason": "already_exists",
            "message": f"ℹ️ Zaten mevcut: {target}",
            "source": str(source),
            "target": str(target),
            "generated_secrets": {},
        }

    rendered, generated = render_env_template(
        source.read_text(encoding="utf-8"),
        profile=source.stem.removeprefix(".env."),
        generate_secrets=generate_secrets,
    )
    target.write_text(rendered, encoding="utf-8")
    try:
        target.chmod(0o600)
    except OSError:
        # chmod is best-effort on platforms/filesystems that support POSIX modes.
        pass
    return {
        "profile": profile,
        "created": True,
        "reason": "created" if not force else "overwritten",
        "message": f"✅ Oluşturuldu: {target}" if not force else f"✅ Güncellendi: {target}",
        "source": str(source),
        "target": str(target),
        "generated_secrets": generated,
        "next_steps": [
            f"export SIDAR_ENV={source.stem.removeprefix('.env.')}",
            "uv run python -m core.doctor",
        ],
    }


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Sidar için git-ignored yerel ortam dosyası oluştur",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--profile", default=DEFAULT_PROFILE, help="SIDAR_ENV profili")
    parser.add_argument("--force", action="store_true", help="Mevcut dosyayı yeniden oluştur")
    parser.add_argument(
        "--no-generate-secrets",
        action="store_true",
        help="Şablondaki placeholder secret değerlerini aynen bırak",
    )
    return parser.parse_args(argv)


def _emit_human_feedback(summary: dict[str, Any]) -> None:
    """Emit a concise terminal-friendly status without breaking JSON stdout."""
    message = str(summary.get("message") or "").strip()
    if message:
        print(message, file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    summary = bootstrap_profile_env(
        str(args.profile),
        force=bool(args.force),
        generate_secrets=not bool(args.no_generate_secrets),
    )
    _emit_human_feedback(summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
