"""Run Bandit and prevent line-level security suppressions from increasing."""

from __future__ import annotations

import argparse
import datetime as dt
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


def _reduction_targets(path: Path) -> list[tuple[dt.date, int]]:
    """Read and validate the dated, strictly decreasing suppression roadmap."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    initial = payload.get("maximum_skipped_tests")
    raw_targets = payload.get("reduction_targets")
    if not isinstance(initial, int) or not isinstance(raw_targets, list) or not raw_targets:
        raise ValueError("reduction_targets boş olmayan bir liste olmalıdır")
    targets: list[tuple[dt.date, int]] = []
    previous_limit = initial
    for item in raw_targets:
        if not isinstance(item, dict):
            raise ValueError("reduction_targets girdileri object olmalıdır")
        try:
            due_date = dt.date.fromisoformat(item["due_date"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("reduction target due_date YYYY-MM-DD olmalıdır") from exc
        limit = item.get("maximum_skipped_tests")
        if not isinstance(limit, int) or isinstance(limit, bool) or not 0 <= limit < previous_limit:
            raise ValueError("reduction target limitleri negatif olmadan kesin azalmalıdır")
        if targets and due_date <= targets[-1][0]:
            raise ValueError("reduction target tarihleri kesin artmalıdır")
        targets.append((due_date, limit))
        previous_limit = limit
    return targets


def _debt_plan(path: Path) -> tuple[str, tuple[str, ...]]:
    """Return and validate the accountable, ordered suppression review plan."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    plan = payload.get("debt_plan")
    if not isinstance(plan, dict):
        raise ValueError("debt_plan object olmalıdır")
    owner = plan.get("owner")
    review_order = plan.get("review_order")
    rule = plan.get("rule")
    if not isinstance(owner, str) or not owner.strip():
        raise ValueError("debt_plan.owner boş olmayan string olmalıdır")
    if (
        not isinstance(review_order, list)
        or not review_order
        or any(not isinstance(item, str) or not item.endswith(".py") for item in review_order)
        or len(review_order) != len(set(review_order))
    ):
        raise ValueError("debt_plan.review_order benzersiz Python dosyaları içermelidir")
    if not isinstance(rule, str) or "bulk-remove" not in rule:
        raise ValueError("debt_plan.rule toplu suppression kaldırmayı yasaklamalıdır")
    return owner, tuple(review_order)


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
        targets = _reduction_targets(args.baseline)
        owner, review_order = _debt_plan(args.baseline)
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
    print(
        f"Bandit suppression debt plan: owner={owner}, "
        f"review_order={','.join(review_order)}"
    )
    today = dt.date.today()
    effective_target = next(((date, value) for date, value in targets if date >= today), None)
    if effective_target:
        print(
            "Bandit suppression azaltma hedefi: "
            f"due_date={effective_target[0].isoformat()}, maximum={effective_target[1]}"
        )
    overdue = [(date, value) for date, value in targets if date < today and skipped > value]
    if overdue:
        due_date, target = overdue[-1]
        print(
            f"Bandit suppression azaltma hedefi gecikti: {skipped} > {target} "
            f"(due_date={due_date.isoformat()}). Baseline ratchet gevşetilmedi.",
            file=sys.stderr,
        )
        return 1
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
