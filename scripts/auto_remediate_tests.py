"""Test başarısızlıklarını ajan geri-bildirim döngüsüyle iyileştiren yardımcı script."""

from __future__ import annotations

import argparse
import json
import shlex
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from core.ci_remediation import (
    _extract_root_cause_line,
    _extract_suspected_targets,
    build_ci_remediation_payload,
)


@dataclass
class CommandResult:
    command: str
    returncode: int
    stdout: str
    stderr: str

    @property
    def combined_output(self) -> str:
        return "\n".join(part for part in [self.stdout, self.stderr] if part).strip()


@dataclass
class FailureSignal:
    summary: str
    root_cause: str
    suspected_targets: list[str]
    raw_excerpt: str


def run_command(command: str, cwd: Path) -> CommandResult:
    """Komutu çalıştırır ve çıktı bilgisini normalize eder."""
    completed = subprocess.run(
        shlex.split(command),
        cwd=str(cwd),
        capture_output=True,
        text=True,
        check=False,
    )
    return CommandResult(
        command=command,
        returncode=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
    )


def parse_failure_signal(command_result: CommandResult) -> FailureSignal:
    """Başarısız test çıktısından self-heal için sinyal üretir."""
    output = command_result.combined_output
    lines = [line.strip() for line in output.splitlines() if line.strip()]
    summary = lines[-1] if lines else f"Test komutu başarısız oldu (exit={command_result.returncode})."
    root_cause = _extract_root_cause_line(output, summary)
    suspected_targets = _extract_suspected_targets(output)
    return FailureSignal(
        summary=summary,
        root_cause=root_cause,
        suspected_targets=suspected_targets,
        raw_excerpt=output[-4000:],
    )


def build_remediation_prompt(
    *,
    failure: FailureSignal,
    test_command: str,
    attempt: int,
    max_attempts: int,
) -> str:
    """Coder/QA ajanına gönderilecek remediation prompt'unu üretir."""
    context = {
        "kind": "local_test_failure",
        "workflow_name": "local-run-tests",
        "conclusion": "failure",
        "failure_summary": failure.summary,
        "root_cause_hint": failure.root_cause,
        "log_excerpt": failure.raw_excerpt,
        "suspected_targets": failure.suspected_targets,
        "failed_jobs": ["run_tests"],
    }
    diagnosis = (
        f"Deneme {attempt}/{max_attempts}: `{test_command}` komutu başarısız. "
        "Minimal ve geri alınabilir bir düzeltme öner; yalnızca ilgili dosyaları değiştir."
    )
    remediation = build_ci_remediation_payload(context, diagnosis)
    envelope = {
        "instruction": "Aşağıdaki bağlama göre hataları düzelt ve patch uygula.",
        "test_command": test_command,
        "attempt": attempt,
        "max_attempts": max_attempts,
        "failure": {
            "summary": failure.summary,
            "root_cause": failure.root_cause,
            "suspected_targets": failure.suspected_targets,
        },
        "remediation": remediation,
    }
    return json.dumps(envelope, ensure_ascii=False, indent=2)


def run_fixer(*, fixer_command_template: str, prompt: str, cwd: Path) -> CommandResult:
    """Harici fixer komutunu çalıştırır. Prompt dosyası placeholder ile iletilir."""
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".json", delete=False) as handle:
        handle.write(prompt)
        prompt_path = Path(handle.name)

    command = fixer_command_template.format(prompt_file=str(prompt_path))
    return run_command(command, cwd)


def remediate_loop(
    *,
    test_command: str,
    fixer_command_template: str,
    max_attempts: int,
    cwd: Path,
) -> int:
    """Testleri tekrar tekrar çalıştırıp fixer ile iyileştirmeyi dener."""
    if max_attempts < 1:
        raise ValueError("max_attempts en az 1 olmalı")

    for attempt in range(1, max_attempts + 1):
        test_result = run_command(test_command, cwd)
        print(f"[attempt={attempt}] test returncode={test_result.returncode}")
        if test_result.returncode == 0:
            print("✅ Testler geçti. Self-healing döngüsü tamamlandı.")
            return 0

        failure = parse_failure_signal(test_result)
        print(f"❌ Testler başarısız: {failure.summary}")
        if failure.suspected_targets:
            print(f"🎯 Şüpheli dosyalar: {', '.join(failure.suspected_targets)}")

        if attempt == max_attempts:
            print("⛔ Maksimum deneme sayısına ulaşıldı.")
            return test_result.returncode or 1

        prompt = build_remediation_prompt(
            failure=failure,
            test_command=test_command,
            attempt=attempt,
            max_attempts=max_attempts,
        )
        fix_result = run_fixer(
            fixer_command_template=fixer_command_template,
            prompt=prompt,
            cwd=cwd,
        )
        print(f"[attempt={attempt}] fixer returncode={fix_result.returncode}")
        if fix_result.returncode != 0:
            print("⚠️ Fixer komutu başarısız oldu; bir sonraki denemeye geçiliyor.")

    return 1


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Otonom test remediation döngüsü")
    parser.add_argument(
        "--test-command",
        default="./run_tests.sh",
        help="Her döngüde çalıştırılacak test komutu.",
    )
    parser.add_argument(
        "--fixer-command",
        required=True,
        help=(
            "Hata olduğunda çalıştırılacak komut şablonu. "
            "Prompt dosyası için {prompt_file} placeholder'ı desteklenir."
        ),
    )
    parser.add_argument(
        "--max-attempts",
        type=int,
        default=3,
        help="Maksimum self-healing deneme sayısı.",
    )
    parser.add_argument(
        "--cwd",
        default=".",
        help="Komutların çalıştırılacağı çalışma dizini.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    return remediate_loop(
        test_command=args.test_command,
        fixer_command_template=args.fixer_command,
        max_attempts=args.max_attempts,
        cwd=Path(args.cwd).resolve(),
    )


if __name__ == "__main__":
    raise SystemExit(main())
