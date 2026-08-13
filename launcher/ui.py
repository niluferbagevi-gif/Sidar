"""Interactive terminal UI used by the thin launcher entrypoint."""

from __future__ import annotations

from collections.abc import Callable


def print_banner(*, cyan: str, bold: str, reset: str, green: str) -> None:
    """Render the launcher welcome banner without owning startup orchestration."""
    banner = f"""{cyan}{bold}
 ╔══════════════════════════════════════════════╗
 ║  ███████╗██╗██████╗  █████╗ ██████╗          ║
 ║  ██╔════╝██║██╔══██╗██╔══██╗██╔══██╗         ║
 ║  ███████╗██║██║  ██║███████║██████╔╝         ║
 ║  ╚════██║██║██║  ██║██╔══██║██╔══██╗         ║
 ║  ███████║██║██████╔╝██║  ██║██║  ██║         ║
 ║  ╚══════╝╚═╝╚═════╝ ╚═╝  ╚═╝╚═╝  ╚═╝         ║
 ║         SİDAR AKILLI BAŞLATICI               ║
 ╚══════════════════════════════════════════════╝{reset}
    """
    print(banner)
    print(f"{green}Hoş geldiniz! Lütfen Sidar'ı nasıl başlatmak istediğinizi seçin.{reset}\n")


def ask_choice(
    prompt: str,
    options: dict[str, tuple[str, str]],
    default_key: str,
    *,
    default_badge: str | None,
    input_fn: Callable[[str], str],
    yellow: str,
    bold: str,
    reset: str,
    cyan: str,
    green: str,
    magenta: str,
) -> str:
    """Prompt until a known option or the configured default is selected."""
    print(f"{yellow}{bold}{prompt}{reset}")
    for key, (description, _value) in options.items():
        badge = f" {green}({default_badge or 'Varsayılan'}){reset}" if key == default_key else ""
        print(f"  {cyan}[{key}]{reset} {description}{badge}")
    while True:
        choice = input_fn(f"\n{bold}Seçiminiz [{'/'.join(options.keys())}]: {reset}").strip()
        if not choice:
            return options[default_key][1]
        if choice in options:
            return options[choice][1]
        print(f"{magenta}Geçersiz seçim. Lütfen tekrar deneyin.{reset}")


def ask_text(
    prompt: str,
    default: str,
    *,
    default_badge: str | None,
    input_fn: Callable[[str], str],
    yellow: str,
    bold: str,
    reset: str,
    cyan: str,
    green: str,
) -> str:
    """Read a text value while preserving an optional default."""
    if default:
        badge = f" {green}({default_badge}){reset}" if default_badge else ""
        suffix = f" {cyan}[{default}]{reset}{badge}"
    else:
        suffix = ""
    return input_fn(f"{yellow}{bold}{prompt}{reset}{suffix}: ").strip() or default


def confirm(
    prompt: str,
    default_yes: bool,
    *,
    input_fn: Callable[[str], str],
    yellow: str,
    bold: str,
    reset: str,
    cyan: str,
) -> bool:
    """Read a localized yes/no confirmation."""
    hint = "[Y/n]" if default_yes else "[y/N]"
    raw = input_fn(f"\n{yellow}{bold}{prompt}{reset} {cyan}{hint}{reset}: ").strip().lower()
    if not raw:
        return default_yes
    return raw in {"y", "yes", "e", "evet"}
