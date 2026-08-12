"""Run Bandit and prevent line-level security suppressions from increasing."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_BASELINE = ROOT / "bandit-suppression-baseline.json"


def _baseline_limit(path: Path) -> int:
    payload = json.loads(path.read_text(encoding="utf-8"))
    limit = payload.get("maximum_skipped_tests")
    if not isinstance(limit, int) or isinstance(limit, bool) or limit < 0:
        raise ValueError("maximum_skipped_tests negatif olmayan integer olmalıdır")
    return limit


def _skipped_tests(path: Path) -> int:
    payload = json.loads(path.read_text(encoding="utf-8"))
    skipped = payload.get("metrics", {}).get("_totals", {}).get("skipped_tests")
    if not isinstance(skipped, int) or isinstance(skipped, bool) or skipped < 0:
        raise ValueError("Bandit JSON metrics._totals.skipped_tests alanı geçersiz")
    return skipped


def main(argv: list[str] | None = None) -> int:
    """Run the canonical Bandit scan and enforce its suppression ratchet."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE)
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args(argv)

    try:
        limit = _baseline_limit(args.baseline)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"Bandit suppression baseline geçersiz: {exc}", file=sys.stderr)
        return 2

    with tempfile.TemporaryDirectory(prefix="sidar-bandit-") as directory:
        report = Path(directory) / "bandit.json"
        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "bandit",
                "-r",
                ".",
                "-c",
                "pyproject.toml",
                "-x",
                "scripts/ci/check_bandit_suppression_baseline.py",
                "-f",
                "json",
                "-o",
                str(report),
            ],
            cwd=args.root,
            check=False,
        )
        try:
            skipped = _skipped_tests(report)
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            print(f"Bandit suppression metriği okunamadı: {exc}", file=sys.stderr)
            return completed.returncode or 2

    print(f"Bandit suppression ratchet: skipped_tests={skipped}, maximum={limit}")
    if skipped > limit:
        print(
            f"Bandit suppression sayısı arttı: {skipped} > {limit}. "
            "Yeni # nosec eklemek yerine bulguyu giderin veya baseline değişikliğini inceletin.",
            file=sys.stderr,
        )
        return 1
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
