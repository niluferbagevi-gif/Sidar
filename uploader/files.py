"""Upload file selection: forbidden/generated path filtering and safe file collection.

Extracted from ``github_upload.py``; collaborators are injected by its wrappers.
"""

from __future__ import annotations

import os
import re
from collections.abc import Callable

# ASLA YÜKLENMEMESİ GEREKENLER (kritik güvenlik katmanı)
FORBIDDEN_PATHS = [
    ".env",
    ".sidar_keys.env",
    ".sidar_keys.env.",
    "sessions/",
    "chroma_db/",
    "__pycache__/",
    ".git/",
    "logs/",
    "models/",
]

GENERATED_ARTIFACT_PATHS = {
    "coverage.json",
    "coverage.xml",
    "coverage-final.json",
    "htmlcov/",
    "artifacts/",
    "web_ui_react/coverage/",
    "web_ui_react/playwright-report/",
    "web_ui_react/test-results/",
}

CONFLICT_MARKER_RE = re.compile(r"^<{7}(?:\s|$)|^={7}$|^>{7}(?:\s|$)", re.MULTILINE)


def normalize_path(path: str) -> str:
    """Yol formatını güvenlik kontrolleri için normalize eder."""
    normalized = path.replace("\\", "/")
    if normalized.startswith("./"):
        normalized = normalized[2:]
    elif normalized.startswith("/"):
        normalized = normalized[1:]
    while "//" in normalized:
        normalized = normalized.replace("//", "/")
    normalized = normalized.lstrip("/")
    return normalized


def is_forbidden_path(path: str, *, _normalize_path: Callable[..., str]) -> bool:
    """Hard blacklist: .gitignore'dan bağımsız kesin engel."""
    normalized = _normalize_path(path)

    # .env*.example dosyalarının güvenlik filtresine takılmasını önleyen istisna
    # Örn: .env.example, .env.test.example, .env.prod.example
    base_name = os.path.basename(normalized)
    if base_name.startswith(".env") and base_name.endswith(".example"):
        return False

    blocked_paths = [*FORBIDDEN_PATHS, *GENERATED_ARTIFACT_PATHS]
    return any(
        normalized == forbidden.rstrip("/") or normalized.startswith(forbidden)
        for forbidden in blocked_paths
    )


def get_file_content(path: str, *, is_forbidden_path: Callable[..., bool]) -> str | None:
    """UTF-8 güvenli okuma; binary/hatalı dosyaları atlar."""
    if is_forbidden_path(path):
        return None

    try:
        with open(path, encoding="utf-8") as file:
            return file.read()
    except (UnicodeDecodeError, OSError):
        return None


def has_conflict_markers(path: str, *, get_file_content: Callable[..., str | None]) -> bool:
    """Metin dosyasında kalmış klasik merge conflict marker satırlarını tespit eder."""
    content = get_file_content(path)
    return bool(content and CONFLICT_MARKER_RE.search(content))


def collect_safe_files(
    deleted_files_list: list[str] | None = None,
    *,
    get_file_content: Callable[..., str | None],
    has_conflict_markers: Callable[..., bool],
    is_forbidden_path: Callable[..., bool],
    run_command: Callable[..., tuple[bool, str]],
) -> tuple[list[str], list[str]]:
    """Yalnızca güvenli dosyaları stage listesine alır."""
    if deleted_files_list is None:
        deleted_files_list = []

    success, output = run_command(
        ["git", "ls-files", "-co", "--exclude-standard"], show_output=False
    )
    if not success:
        return [], []

    safe_files = []
    blocked_files = []

    TEXT_EXTENSIONS = {
        ".py",
        ".md",
        ".txt",
        ".json",
        ".yml",
        ".yaml",
        ".html",
        ".css",
        ".js",
        ".sh",
        ".csv",
        ".example",
    }

    for line in output.splitlines():
        file_path = line.strip()
        if not file_path:
            continue
        if os.path.isdir(file_path):
            continue
        if file_path in deleted_files_list:
            continue

        if is_forbidden_path(file_path):
            blocked_files.append(file_path)
            continue

        _, ext = os.path.splitext(file_path)
        if ext.lower() in TEXT_EXTENSIONS:
            if get_file_content(file_path) is None:
                blocked_files.append(file_path)
                continue
            if has_conflict_markers(file_path):
                blocked_files.append(file_path)
                continue

        safe_files.append(file_path)

    return safe_files, blocked_files
