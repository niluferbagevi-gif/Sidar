"""Repository standards and built-in role contract reporting for Sidar.

The report is intentionally read-only: it helps CI and maintainers detect drift
between AGENTS.md operational rules, built-in role exports, registry contracts,
and user-facing documentation snippets before a new role or docs change lands.
"""

from __future__ import annotations

import argparse
import ast
import json
import logging
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
LOW_HARDWARE_MODEL_PATTERN = re.compile(
    r"qwen2\.5-coder:(?:0\.5b|1\.5b|3b)", re.IGNORECASE
)
DEFAULT_WORD_PATTERN = re.compile(r"\b(default|varsayılan|standard|standart)\b", re.IGNORECASE)
PIP_INSTALL_PATTERN = re.compile(r"(?:^|\s)(?:python\S*\s+-m\s+)?pip\s+install\b")
UV_PIP_INSTALL_PATTERN = re.compile(r"(?:^|\s)uv\s+pip\s+install\b")


@dataclass(frozen=True)
class StandardsViolation:
    code: str
    path: str
    line: int
    text: str
    message: str


@dataclass(frozen=True)
class RoleContractStatus:
    role_name: str
    class_name: str
    module_name: str
    capabilities: list[str]
    supervisor_intents: list[str]
    swarm_intents: list[str]
    role_file_exists: bool
    exported_in_roles_init: bool
    present_in_bootstrap_imports: bool
    documented_in_agents: bool
    checklist: dict[str, bool]


def _repo_relative(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _extract_roles_init_exports(path: Path = REPO_ROOT / "agent/roles/__init__.py") -> set[str]:
    tree = ast.parse(_read_text(path), filename=str(path))
    exports: set[str] = set()
    for node in tree.body:
        if not (
            isinstance(node, ast.Assign)
            and any(isinstance(target, ast.Name) and target.id == "__all__" for target in node.targets)
            and isinstance(node.value, ast.List)
        ):
            continue
        exports = {item.value for item in node.value.elts if isinstance(item, ast.Constant)}
        break
    return exports


def _extract_bootstrap_imports(path: Path = REPO_ROOT / "agent/registry.py") -> set[str]:
    tree = ast.parse(_read_text(path), filename=str(path))
    imports: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef) or node.name != "_import_builtin_roles":
            continue
        for stmt in ast.walk(node):
            if not (
                isinstance(stmt, ast.Assign)
                and any(
                    isinstance(target, ast.Name) and target.id == "builtin_role_modules"
                    for target in stmt.targets
                )
                and isinstance(stmt.value, ast.Tuple)
            ):
                continue
            imports = {item.value for item in stmt.value.elts if isinstance(item, ast.Constant)}
            break
    return imports


def build_role_contract_report() -> dict[str, Any]:
    """Return a structured built-in role drift report."""
    from agent.registry import BUILTIN_ROLE_CONTRACTS

    role_exports = _extract_roles_init_exports()
    bootstrap_imports = _extract_bootstrap_imports()
    agents_text = _read_text(REPO_ROOT / "AGENTS.md")

    roles: list[RoleContractStatus] = []
    for contract in BUILTIN_ROLE_CONTRACTS:
        role_file = REPO_ROOT / (contract.module_name.replace(".", "/") + ".py")
        checklist = {
            "role_file": role_file.exists(),
            "roles_init_export": contract.class_name in role_exports,
            "registry_contract": True,
            "bootstrap_import": contract.module_name in bootstrap_imports,
            "supervisor_intent": bool(contract.supervisor_intents),
            "swarm_intent": bool(contract.swarm_intents),
            "agents_docs": contract.class_name in agents_text,
        }
        roles.append(
            RoleContractStatus(
                role_name=contract.role_name,
                class_name=contract.class_name,
                module_name=contract.module_name,
                capabilities=list(contract.capabilities),
                supervisor_intents=list(contract.supervisor_intents),
                swarm_intents=list(contract.swarm_intents),
                role_file_exists=checklist["role_file"],
                exported_in_roles_init=checklist["roles_init_export"],
                present_in_bootstrap_imports=checklist["bootstrap_import"],
                documented_in_agents=checklist["agents_docs"],
                checklist=checklist,
            )
        )

    drift = [asdict(role) for role in roles if not all(role.checklist.values())]
    return {
        "status": "drift" if drift else "ok",
        "roles": [asdict(role) for role in roles],
        "drift": drift,
        "checklist_items": [
            "role_file",
            "roles_init_export",
            "registry_contract",
            "bootstrap_import",
            "supervisor_intent",
            "swarm_intent",
            "agents_docs",
            "tests",
        ],
    }


def scan_repo_standards(
    paths: list[Path], *, legacy_product_names: list[str] | None = None
) -> list[StandardsViolation]:
    """Scan selected user-facing files for AGENTS.md standard drift."""
    violations: list[StandardsViolation] = []
    legacy_names = [name for name in (legacy_product_names or []) if name]
    for path in paths:
        if path.is_dir():
            files = [item for item in path.rglob("*") if item.is_file()]
        else:
            files = [path]
        for file_path in files:
            if file_path.suffix.lower() not in {".md", ".rst", ".txt", ".sh", ".yml", ".yaml"}:
                continue
            try:
                lines = _read_text(file_path).splitlines()
            except UnicodeDecodeError:
                continue
            for line_no, line in enumerate(lines, start=1):
                if PIP_INSTALL_PATTERN.search(line) and not UV_PIP_INSTALL_PATTERN.search(line):
                    violations.append(
                        StandardsViolation(
                            code="direct-pip-install",
                            path=_repo_relative(file_path),
                            line=line_no,
                            text=line.strip(),
                            message="Use `uv pip install` in Sidar docs/scripts instead of direct pip install.",
                        )
                    )
                if LOW_HARDWARE_MODEL_PATTERN.search(line) and DEFAULT_WORD_PATTERN.search(line):
                    violations.append(
                        StandardsViolation(
                            code="low-hardware-model-default",
                            path=_repo_relative(file_path),
                            line=line_no,
                            text=line.strip(),
                            message="Do not document low-hardware qwen2.5-coder fallbacks as Sidar defaults.",
                        )
                    )
                for legacy_name in legacy_names:
                    if legacy_name in line:
                        violations.append(
                            StandardsViolation(
                                code="legacy-product-name",
                                path=_repo_relative(file_path),
                                line=line_no,
                                text=line.strip(),
                                message=f"Legacy product name `{legacy_name}` appears in a scanned file.",
                            )
                        )
    return violations


def build_report(
    *, standards_paths: list[Path] | None = None, legacy_product_names: list[str] | None = None
) -> dict[str, Any]:
    violations = scan_repo_standards(
        standards_paths or [], legacy_product_names=legacy_product_names or []
    )
    role_report = build_role_contract_report()
    return {
        "status": "fail" if violations or role_report["status"] != "ok" else "ok",
        "role_contracts": role_report,
        "repo_standards": {
            "status": "fail" if violations else "ok",
            "violations": [asdict(item) for item in violations],
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Sidar repo standards and role contract report")
    parser.add_argument(
        "--standards-path",
        action="append",
        default=[],
        help="File or directory to scan for AGENTS.md standards drift. Can be repeated.",
    )
    parser.add_argument(
        "--legacy-product-name",
        action="append",
        default=[],
        help="Legacy product token to flag in scanned user-facing files. Can be repeated.",
    )
    parser.add_argument("--format", choices=("json", "text"), default="json")
    parser.add_argument("--fail-on-violation", action="store_true")
    args = parser.parse_args(argv)

    logging.disable(logging.CRITICAL)
    report = build_report(
        standards_paths=[Path(item) for item in args.standards_path],
        legacy_product_names=list(args.legacy_product_name),
    )
    if args.format == "json":
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(f"status={report['status']}")
        print(f"role_contracts={report['role_contracts']['status']}")
        print(f"repo_standards={report['repo_standards']['status']}")
    return 1 if args.fail_on_violation and report["status"] != "ok" else 0


if __name__ == "__main__":  # pragma: no cover - CLI entrypoint
    raise SystemExit(main())
