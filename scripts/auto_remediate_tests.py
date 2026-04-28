"""Mypy hataları için ajan destekli otonom remediation döngüsü."""

from __future__ import annotations

import argparse
import asyncio
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from config import Config

if TYPE_CHECKING:
    from agent.roles.qa_agent import QAAgent

_MYPY_ERROR_RE = re.compile(
    r"^(?P<path>.*?\.py):(?P<line>\d+)(?::(?P<col>\d+))?: error: (?P<message>.*)$",
    re.MULTILINE,
)


@dataclass(slots=True)
class ParsedError:
    """Tek bir mypy error satırı için normalize edilmiş temsil."""

    path: str
    line: int
    raw_line: str


def run_mypy() -> tuple[int, str]:
    """Mypy komutunu çalıştırır ve birleşik çıktıyı döndürür."""
    result = subprocess.run(
        ["uv", "run", "mypy", "."],
        capture_output=True,
        text=True,
        check=False,
    )
    output = "\n".join(part for part in (result.stdout, result.stderr) if part).strip()
    return result.returncode, output


def parse_mypy_errors(output: str) -> dict[str, list[ParsedError]]:
    """Mypy çıktısını dosya bazında gruplayarak ayrıştırır."""
    grouped: dict[str, list[ParsedError]] = {}
    for match in _MYPY_ERROR_RE.finditer(str(output or "")):
        path = match.group("path").strip()
        line = int(match.group("line"))
        parsed = ParsedError(path=path, line=line, raw_line=match.group(0).strip())
        grouped.setdefault(path, []).append(parsed)
    return grouped


def _slice_file_window(source: str, lines: list[int], radius: int = 60) -> str:
    """Büyük dosyalarda bağlam penceresini sınırlar."""
    raw_lines = source.splitlines()
    if not raw_lines:
        return source
    start = max(min(lines) - radius - 1, 0)
    end = min(max(lines) + radius, len(raw_lines))
    numbered = [f"{idx + 1}: {raw_lines[idx]}" for idx in range(start, end)]
    return "\n".join(numbered)


def _strip_markdown_fences(raw: str) -> str:
    text = str(raw or "").strip()
    if not text.startswith("```"):
        return text
    lines = text.splitlines()
    if len(lines) <= 1:
        return text
    body = lines[1:]
    if body and body[-1].strip().startswith("```"):
        body = body[:-1]
    return "\n".join(body).strip()


class AutoRemediator:
    """Mypy hata loglarını ajan tabanlı loop ile iyileştirir."""

    def __init__(self, *, max_retries: int = 3) -> None:
        from agent.roles.qa_agent import QAAgent

        self.max_retries = max(1, int(max_retries))
        self.qa_agent: QAAgent = QAAgent(Config())

    async def _fix_file(self, filepath: str, errors: list[ParsedError]) -> bool:
        target = Path(filepath)
        if not target.exists():
            print(f"⚠️ Dosya bulunamadı, atlanıyor: {filepath}")
            return False

        original = target.read_text(encoding="utf-8")
        line_numbers = [item.line for item in errors]
        context_window = _slice_file_window(original, line_numbers)
        error_log = "\n".join(item.raw_line for item in errors)
        prompt = (
            "Aşağıdaki Python dosyasında mypy type hataları var.\n\n"
            f"Dosya: {filepath}\n"
            f"Hatalar:\n{error_log}\n\n"
            "Kurallar:\n"
            "- Yalnızca gerekli minimal düzeltmeleri yap.\n"
            "- İş mantığını değiştirme.\n"
            "- Sadece dosyanın TAM ve düzeltilmiş içeriğini döndür.\n"
            "- Markdown veya açıklama döndürme.\n\n"
            f"Bağlam penceresi:\n{context_window}\n\n"
            f"Orijinal dosya içeriği:\n{original}"
        )
        try:
            fixed = await self.qa_agent.call_llm(
                messages=[{"role": "user", "content": prompt}],
                system_prompt=(
                    "Sen kıdemli bir Python bakım mühendisisin. "
                    "Mypy hatalarını minimum değişiklikle düzeltirsin."
                ),
                temperature=0.0,
            )
        except Exception as exc:  # pragma: no cover - provider bağımlı
            print(f"❌ LLM çağrısı başarısız ({filepath}): {exc}")
            return False

        cleaned = _strip_markdown_fences(fixed)
        if not cleaned or cleaned == original:
            print(f"⚠️ {filepath} için uygulanabilir değişiklik üretilmedi.")
            return False

        target.write_text(cleaned + ("\n" if not cleaned.endswith("\n") else ""), encoding="utf-8")
        print(f"✅ Onarıldı: {filepath}")
        return True

    async def remediate_loop(self) -> bool:
        for attempt in range(1, self.max_retries + 1):
            print(f"\n--- Otonom remediation denemesi {attempt}/{self.max_retries} ---")
            code, output = run_mypy()
            if code == 0:
                print("🎉 Mypy başarıyla geçti.")
                return True

            grouped = parse_mypy_errors(output)
            if not grouped:
                print("❌ Mypy başarısız fakat ayrıştırılabilir hata bulunamadı.")
                print(output[:1500])
                return False

            print(f"⚠️ {sum(len(v) for v in grouped.values())} hata bulundu, remediation başlıyor...")
            changed = False
            for path, file_errors in grouped.items():
                changed = await self._fix_file(path, file_errors) or changed

            if not changed:
                print("❌ Remediation değişiklik üretemedi, döngü sonlandırılıyor.")
                return False

        print("❌ Maksimum deneme sayısına ulaşıldı; mypy halen başarısız.")
        return False


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Ajan destekli mypy remediation döngüsü")
    parser.add_argument("--max-retries", type=int, default=3, help="Maksimum remediation denemesi")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    ok = asyncio.run(AutoRemediator(max_retries=args.max_retries).remediate_loop())
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
