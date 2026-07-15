"""Shell-independent command argument construction helpers."""

from __future__ import annotations

import logging
import os
import re
import shlex
import shutil
import subprocess  # nosec B404
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)


def build_sanitized_shell_args(
    command: str,
    *,
    allow_shell_features: bool,
    find_executable: Callable[[str], str | None],
) -> list[str]:
    """Return a validated argv list without enabling subprocess shell parsing."""
    if "\x00" in command:
        raise ValueError("Komut NUL baytı içeremez.")

    if allow_shell_features:
        interpreter = find_executable("bash") or find_executable("sh")
        if not interpreter:
            raise ValueError("Shell özellikleri için bash/sh yorumlayıcısı bulunamadı.")
        return [interpreter, "-lc", command]

    args = shlex.split(command)
    if not args:
        raise ValueError("Komut bağımsız değişkenlere ayrıştırılamadı.")
    if any("\x00" in arg for arg in args):  # pragma: no cover - guarded above
        raise ValueError("Komut argümanları NUL baytı içeremez.")
    return args


# ── Yıkıcı komut kalıp tespiti (allow_shell_features=True yolu) ─────────────
#
# ÖNEMLİ SINIR: allow_shell_features=True olduğunda komut gerçek bir kabukla
# (`bash -lc`) çalıştırılır; bu yüzden burada yapılan statik analiz asla tam
# bir güvenlik sınırı OLAMAZ. Değişken/komut ikamesi (`$x`, `$(...)`, backtick),
# base64/eval zincirleri veya eşdeğer bir aracın kullanılması, önceden metin
# üzerinde çalışan HERHANGİ bir statik kontrolü prensipte atlatabilir — bu,
# rastgele kabuk çalıştırmaya izin vermenin doğal sonucudur. Aşağıdaki kontrol,
# kazara/dikkatsiz yıkıcı komutlara (LLM halüsinasyonu, yanlış kopyala-yapıştır)
# karşı en iyi çaba (best-effort) bir güvenlik ağıdır; kötü niyetli, bilinçli
# atlatmaya karşı garanti vermez. Buna rağmen önceki sabit alt-dizge eşleşmesi
# (`"rm -rf /" in command.lower()`) boşluk/bayrak sırası farklılıklarıyla bile
# (`"rm  -rf  /"`, `"rm -r -f /"`, `"rm --recursive --force /"`) trivially
# atlatılabiliyordu; buradaki token bazlı kontrol bu sınıfı kapatır ve ayrıca
# statik olarak çözülemeyen (`$değişken`, `$(...)`, backtick) segmentlerde
# yıkıcı komut adı geçiyorsa fail-closed olarak engeller.
_LEGACY_BLOCKED_SUBSTRINGS = (
    ":(){ :|:& };",
    "> /etc/passwd",
    "> /etc/shadow",
    "> /dev/sda",
)
_DYNAMIC_EXPANSION_RE = re.compile(r"\$\(|`|\$\{|\$[A-Za-z_][A-Za-z0-9_]*")
_SEGMENT_SPLIT_RE = re.compile(r"&&|\|\||[;&|\n]")
_MKFS_RE = re.compile(r"\bmkfs(\.\w+)?\b")
_DEV_WIPE_RE = re.compile(r"\b(shred|wipefs)\b.*?/dev/")
_DESTRUCTIVE_COMMAND_NAMES = {"rm", "dd", "shred", "wipefs", "chmod", "chown"}
HOME_SHORTHAND = "~"
_CATASTROPHIC_TARGETS = {"/", "/*", "~", "$home", "*", "/root", "/root/*", "/home", "/home/*"}
_RECURSIVE_FLAGS = {"r", "recursive"}
_FORCE_FLAGS = {"f", "force"}
_CHMOD_WORLD_WRITABLE_MODES = {"777", "0777", "a+rwx", "ugo+rwx"}


def _shell_token_flags(tokens: list[str]) -> set[str]:
    """Return normalized flag names from an argv tail (handles -rf and --force)."""
    flags: set[str] = set()
    for token in tokens:
        if token.startswith("--"):
            flags.add(token[2:].split("=", 1)[0].lower())
        elif token.startswith("-") and len(token) > 1:
            flags.update(token[1:].lower())
    return flags


def find_destructive_shell_pattern(command: str) -> str | None:
    """Return a description of a detected destructive command, or None if clean.

    Best-effort safety net only — see module note above for why this cannot be
    a complete security boundary once arbitrary shell evaluation is enabled.
    """
    whole_lowered = command.lower()
    for pattern in _LEGACY_BLOCKED_SUBSTRINGS:
        if pattern in whole_lowered:
            return pattern

    for raw_segment in _SEGMENT_SPLIT_RE.split(command):
        segment = raw_segment.strip()
        if not segment:
            continue
        lowered = segment.lower()

        if _MKFS_RE.search(lowered):
            return "mkfs"
        if _DEV_WIPE_RE.search(lowered):
            return "shred/wipefs /dev/*"

        has_dynamic_expansion = bool(_DYNAMIC_EXPANSION_RE.search(segment))
        try:
            tokens = shlex.split(segment)
        except ValueError:
            segment_words = lowered.split(None, 1)
            first_word = segment_words[0].rsplit("/", 1)[-1] if segment_words else ""
            if first_word in _DESTRUCTIVE_COMMAND_NAMES or _MKFS_RE.search(lowered):
                return f"{first_word or 'shell'} + hatalı tırnaklama (statik olarak doğrulanamaz)"
            continue
        if not tokens:
            continue

        command_name = tokens[0].rsplit("/", 1)[-1].lower()
        positional = [token for token in tokens[1:] if not token.startswith("-")]
        flags = _shell_token_flags(tokens[1:])

        if command_name == "rm":
            is_recursive = bool(flags & _RECURSIVE_FLAGS)
            is_forced = bool(flags & _FORCE_FLAGS)
            # Herhangi bir mutlak yol (/...), home (~) veya glob (*) hedefi riskli
            # kabul edilir — yalnızca "/" değil, "rm -rf /tmp" gibi geniş kapsamlı
            # mutlak-yol silmeleri de engellenir (önceki alt-dizge kontrolünün
            # kapsamıyla uyumlu; bkz. testler).
            targets_risky_path = any(
                token.lower() in _CATASTROPHIC_TARGETS
                or token.startswith("/")
                or token == HOME_SHORTHAND
                for token in positional
            )
            if (
                is_recursive
                and is_forced
                and (targets_risky_path or (has_dynamic_expansion and not positional))
            ):
                target_desc = " ".join(positional) or "(değişken/komut ikamesiyle belirlenen hedef)"
                return f"rm -rf {target_desc}"
        elif command_name == "dd" and any(
            token.lower().startswith("of=/dev/") for token in tokens[1:]
        ):
            return "dd of=/dev/*"
        elif command_name == "chmod":
            is_recursive = bool(flags & _RECURSIVE_FLAGS)
            if (
                is_recursive
                and positional
                and positional[0] in _CHMOD_WORLD_WRITABLE_MODES
                and any(token.lower() in _CATASTROPHIC_TARGETS for token in positional[1:])
            ):
                return "chmod -R 777 /"
        elif command_name == "chown":
            is_recursive = bool(flags & _RECURSIVE_FLAGS)
            if is_recursive and any(token.lower() in _CATASTROPHIC_TARGETS for token in positional):
                return "chown -R .../"

        if has_dynamic_expansion and command_name in _DESTRUCTIVE_COMMAND_NAMES:
            return f"{command_name} + değişken/komut ikamesi (statik olarak doğrulanamaz)"

    return None


def run_shell_command(
    manager: Any,
    command: str,
    cwd: str | None = None,
    *,
    allow_shell_features: bool = False,
) -> tuple[bool, str]:
    """Run a local shell command using CodeManager's security and output policy."""
    if not manager.security.can_run_shell():
        return False, (
            "[OpenClaw] Kabuk komutu çalıştırma yetkisi yok.\n"
            "Shell erişimi yalnızca ACCESS_LEVEL=full modunda aktiftir.\n"
            "Değiştirmek için: .env → ACCESS_LEVEL=full"
        )

    if not command or not command.strip():
        return False, "⚠ Çalıştırılacak komut belirtilmedi."

    work_dir = cwd or str(manager.base_dir)

    shell_meta_chars = ("|", "&", ";", ">", "<", "$(", "`")
    uses_shell_features = any(token in command for token in shell_meta_chars)
    if uses_shell_features and not allow_shell_features:
        return False, (
            "⚠ Komut shell operatörleri içeriyor (|, >, &&, vb.).\n"
            "Güvenlik için varsayılan modda bu operatörler kapalıdır.\n"
            "Gerekliyse allow_shell_features=True ile tekrar deneyin."
        )

    if allow_shell_features:
        detected_pattern = find_destructive_shell_pattern(command)
        if detected_pattern is not None:
            return False, (
                f"⛔ Engellendi: tehlikeli kabuk komutu kalıbı algılandı ({detected_pattern!r}). "
                "Bu işlem yıkıcı olabilir ve izin verilmemektedir."
            )

    try:
        if allow_shell_features:
            logger.warning(
                "[GÜVENLİK] Shell özellikleri etkin; Python subprocess shell=True kapalı, "
                "sabit yorumlayıcı argv listesi kullanılacak. "
                "Komut pipe/redirect/subshell içerebilir — yalnızca güvenilir kaynaklardan çalıştırılmalıdır. "
                "Komut (ilk 200 kar): %.200s",
                command,
            )
        args = build_sanitized_shell_args(
            command, allow_shell_features=allow_shell_features, find_executable=shutil.which
        )
        result = subprocess.run(  # nosec B603
            args,
            shell=False,
            capture_output=True,
            text=True,
            timeout=60,
            cwd=work_dir,
            env={**os.environ},
        )
        output_parts = []
        if result.stdout.strip():
            output_parts.append(result.stdout.strip())
        if result.stderr.strip():
            output_parts.append(f"[stderr]\n{result.stderr.strip()}")

        combined = "\n".join(output_parts) if output_parts else "(komut çıktı üretmedi)"

        if len(combined) > manager.max_output_chars:
            combined = combined[: manager.max_output_chars] + (
                f"\n\n... [ÇIKTI KIRPILDI: Maksimum {manager.max_output_chars} karakter sınırı aşıldı] ..."
            )

        if result.returncode != 0:
            return False, f"Komut başarısız (çıkış kodu: {result.returncode}):\n{combined}"
        return True, combined

    except ValueError as exc:
        return False, f"Komut ayrıştırılamadı: {exc}"
    except subprocess.TimeoutExpired:
        return False, "⚠ Zaman aşımı! Komut 60 saniyeden uzun sürdü ve durduruldu."
    except Exception as exc:
        return False, f"Kabuk hatası: {exc}"


__all__ = ["build_sanitized_shell_args", "find_destructive_shell_pattern", "run_shell_command"]
