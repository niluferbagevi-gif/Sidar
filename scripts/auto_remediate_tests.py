"""run_tests.sh için otonom iyileştirme döngüsü.

Bu script test komutunu çalıştırır, başarısız olursa çıktıyı ayrıştırıp
remediation payload üretir ve isteğe bağlı fixer komutunu tetikler.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.ci_remediation import build_ci_remediation_payload

_DEFAULT_TEST_COMMAND = "./run_tests.sh"
_DEFAULT_MAX_ATTEMPTS = 3

_TARGET_RE = re.compile(r"(?P<path>(?:tests|core|agent|managers|scripts|web_server)[/\\][\w./-]+)")
_ERROR_RE = re.compile(
    r"(?P<line>.*(?:AssertionError|ModuleNotFoundError|ImportError|TypeError|ValueError|"
    r"SyntaxError|NameError|FAILED|ERROR).*)",
    re.IGNORECASE,
)


@dataclass(slots=True)
class AttemptResult:
    attempt: int
    command: str
    returncode: int
    stdout: str
    stderr: str

    @property
    def combined_output(self) -> str:
        return "\n".join(part for part in (self.stdout, self.stderr) if part)


@dataclass(slots=True)
class FailureParse:
    failure_summary: str
    root_cause_hint: str
    suspected_targets: list[str]
    diagnostic_hints: list[str]


def run_command(command: str, cwd: Path, timeout: int | None = None) -> AttemptResult:
    completed = subprocess.run(  # noqa: S603
        command,
        cwd=str(cwd),
        shell=True,  # noqa: S602
        text=True,
        capture_output=True,
        timeout=timeout,
        check=False,
    )
    return AttemptResult(
        attempt=0,
        command=command,
        returncode=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
    )


def parse_failure_output(output: str) -> FailureParse:
    text = (output or "").strip()
    suspected_targets: list[str] = []
    seen: set[str] = set()
    for match in _TARGET_RE.finditer(text):
        path = match.group("path").replace("\\", "/").strip(" .,;:)")
        if path and path not in seen:
            seen.add(path)
            suspected_targets.append(path)
        if len(suspected_targets) >= 8:
            break

    root_cause_hint = ""
    for line in text.splitlines():
        normalized = line.strip()
        if normalized and _ERROR_RE.match(normalized):
            root_cause_hint = normalized[:220]
            break

    if root_cause_hint:
        failure_summary = root_cause_hint
    elif text:
        failure_summary = text.splitlines()[-1][:220]
    else:
        failure_summary = "Test command failed without output."

    hints: list[str] = []
    lowered = text.lower()
    if "assert" in lowered or "failed" in lowered:
        hints.append("Assertion kaynaklı test kırılması olabilir.")
    if "import" in lowered or "module" in lowered:
        hints.append("Import zinciri ve bağımlılıklar kontrol edilmeli.")
    if "typeerror" in lowered or "valueerror" in lowered:
        hints.append("Tip/şema uyuşmazlığı kontrolü önerilir.")

    return FailureParse(
        failure_summary=failure_summary,
        root_cause_hint=root_cause_hint,
        suspected_targets=suspected_targets,
        diagnostic_hints=hints[:5],
    )


def build_remediation_payload(
    parsed: FailureParse,
    attempt: int,
    max_attempts: int,
    command: str,
    output_excerpt: str,
) -> dict:
    context = {
        "kind": "local_test_failure",
        "workflow_name": "local_self_heal_loop",
        "run_id": f"attempt-{attempt}",
        "failure_summary": parsed.failure_summary,
        "log_excerpt": output_excerpt[:2000],
        "suspected_targets": parsed.suspected_targets,
        "root_cause_hint": parsed.root_cause_hint,
        "diagnostic_hints": parsed.diagnostic_hints,
        "failed_jobs": ["local-tests"],
        "status": "completed",
        "conclusion": "failure",
        "branch": "local",
        "base_branch": "local",
        "repo": "local",
    }
    diagnosis = (
        f"{attempt}/{max_attempts} denemesinde '{command}' başarısız oldu. "
        "Kök nedeni analiz edip minimal ve güvenli patch üret."
    )
    payload = build_ci_remediation_payload(context, diagnosis)
    payload["attempt"] = attempt
    payload["max_attempts"] = max_attempts
    payload["test_command"] = command
    return payload


def _format_attempt_output(result: AttemptResult) -> str:
    header = f"\n===== Attempt {result.attempt}: {result.command} (exit={result.returncode}) ====="
    body = result.combined_output.strip()
    return f"{header}\n{body}\n"


def run_self_heal_loop(
    *,
    test_command: str,
    fixer_command_template: str | None,
    max_attempts: int,
    workdir: Path,
    timeout: int | None,
    payload_dir: Path,
) -> int:
    payload_dir.mkdir(parents=True, exist_ok=True)

    for attempt in range(1, max_attempts + 1):
        result = run_command(test_command, cwd=workdir, timeout=timeout)
        result.attempt = attempt
        print(_format_attempt_output(result))

        if result.returncode == 0:
            print(f"✅ Testler {attempt}. denemede geçti.")
            return 0

        parsed = parse_failure_output(result.combined_output)
        payload = build_remediation_payload(
            parsed,
            attempt=attempt,
            max_attempts=max_attempts,
            command=test_command,
            output_excerpt=result.combined_output,
        )

        payload_file = payload_dir / f"remediation_attempt_{attempt}.json"
        payload_file.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        attempt_meta = {
            "attempt": attempt,
            "command": result.command,
            "returncode": result.returncode,
            "failure": asdict(parsed),
            "payload_file": str(payload_file),
        }
        print(json.dumps(attempt_meta, ensure_ascii=False, indent=2))

        if not fixer_command_template:
            print("⚠️ fixer-command belirtilmediği için otonom düzeltme adımı atlandı.")
            break

        fixer_command = fixer_command_template.format(
            payload_file=payload_file,
            attempt=attempt,
            max_attempts=max_attempts,
        )
        fixer_result = run_command(fixer_command, cwd=workdir, timeout=timeout)
        fixer_result.attempt = attempt
        print(_format_attempt_output(fixer_result))

    print(f"❌ Maksimum deneme sayısına ulaşıldı ({max_attempts}).")
    return 1


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="run_tests.sh için otonom self-heal döngüsü")
    parser.add_argument("--test-command", default=_DEFAULT_TEST_COMMAND)
    parser.add_argument(
        "--fixer-command",
        default=None,
        help=(
            "Başarısız testten sonra çalışacak komut şablonu. "
            "{payload_file}, {attempt}, {max_attempts} placeholderlarını destekler."
        ),
    )
    parser.add_argument("--max-attempts", type=int, default=_DEFAULT_MAX_ATTEMPTS)
    parser.add_argument("--timeout", type=int, default=None)
    parser.add_argument("--workdir", type=Path, default=Path("."))
    parser.add_argument("--payload-dir", type=Path, default=Path("artifacts/self_heal"))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.max_attempts < 1:
        raise SystemExit("--max-attempts en az 1 olmalıdır.")

    return run_self_heal_loop(
        test_command=str(args.test_command),
        fixer_command_template=(
            str(args.fixer_command).strip() if args.fixer_command is not None else None
        ),
        max_attempts=int(args.max_attempts),
        workdir=Path(args.workdir),
        timeout=args.timeout,
        payload_dir=Path(args.payload_dir),
    )


if __name__ == "__main__":
    raise SystemExit(main())
