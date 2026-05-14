"""Coverage açığını kapatmak için otonom test üretimi yapan ajan."""

from __future__ import annotations

import ast
import asyncio
import configparser
import contextlib
import hashlib
import inspect
import json
import logging
import re
import shlex
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

import defusedxml.ElementTree as ET

from agent.base_agent import BaseAgent
from agent.registry import AgentCatalog
from config import Config
from core.test_fixture_policy import SHARED_TEST_FIXTURE_GUIDANCE


@AgentCatalog.register(
    capabilities=["coverage_analysis", "pytest_output_analysis", "autonomous_test_generation"],
    description=(
        "Pytest/coverage çıktısından eksik senaryoları bulup deterministik test üreten ajan."
    ),
    is_builtin=True,
)
class CoverageAgent(BaseAgent):
    """Pytest çıktısını okuyup eksik senaryoları belirleyen ve reviewer onayına sunan ajan."""

    SYSTEM_PROMPT = (
        "Sen Coverage Agent rolündesin. Pytest ve coverage çıktısını okuyup eksik senaryoları "
        "tespit eder, deterministik pytest testleri üretir ve reviewer onayına sunarsın."
    )

    TEST_GENERATION_PROMPT = (
        "Yalnızca çalıştırılabilir pytest kodu üret. Ağ erişimi veya dış servis bağımlılığı kullanma. "
        f"{SHARED_TEST_FIXTURE_GUIDANCE} "
        "Yanıtında markdown çiti kullanma."
    )

    def __init__(
        self,
        cfg: Config | None = None,
        *,
        config: Config | None = None,
    ) -> None:
        resolved_cfg = cfg or config
        super().__init__(cfg=resolved_cfg, role_name="coverage")
        from managers.code_manager import CodeManager
        from managers.security import SecurityManager

        self.security = SecurityManager(cfg=self.cfg)
        self.code = CodeManager(self.security, base_dir=self.cfg.BASE_DIR)
        self._db: Any | None = None
        self._db_lock: asyncio.Lock | None = None
        self.register_tool("run_pytest", self._tool_run_pytest)
        self.register_tool("analyze_pytest_output", self._tool_analyze_pytest_output)
        self.register_tool("analyze_coverage_report", self._tool_analyze_coverage_report)
        self.register_tool("analyze_test_artifacts", self._tool_analyze_test_artifacts)
        self.register_tool("generate_missing_tests", self._tool_generate_missing_tests)
        self.register_tool("write_missing_tests", self._tool_write_missing_tests)
        self.register_tool("autonomous_batch_heal", self._tool_autonomous_batch_heal)

    async def _ensure_db(self) -> Any:
        if self._db is not None:
            return self._db
        if self._db_lock is None:
            self._db_lock = asyncio.Lock()
        async with self._db_lock:
            if self._db is not None:
                return self._db
            from core.db import Database

            self._db = Database(self.cfg)
            await self._db.connect()
            await self._db.init_schema()
            return self._db

    @staticmethod
    async def _call_maybe_async(func: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        """Hem senkron hem async tool yardımcılarını güvenli şekilde çalıştır."""
        result = func(*args, **kwargs)
        if inspect.isawaitable(result):
            return await result
        return result

    @staticmethod
    def _extract_test_function_names(source: str) -> set[str]:
        """Python test kodundaki test_* fonksiyon adlarını AST ile çıkarır."""
        tree = ast.parse(str(source or "") or "\n")
        return {
            node.name
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
            and node.name.startswith("test_")
        }

    @staticmethod
    def _build_finding_batches(
        findings: list[dict[str, Any]],
        *,
        batch_size: int,
        max_findings: int | None = None,
    ) -> list[list[dict[str, Any]]]:
        """Coverage bulgularını dosya sırasını koruyan deterministik batch kuyruğuna böler."""
        normalized_batch_size = max(1, int(batch_size or 1))
        capped_findings = list(findings[: max(0, int(max_findings))] if max_findings else findings)
        return [
            capped_findings[index : index + normalized_batch_size]
            for index in range(0, len(capped_findings), normalized_batch_size)
        ]

    @staticmethod
    def _normalize_exclude_files(exclude_files: list[str] | str | None) -> list[str]:
        """Otonom coverage kuyruğu için boş değerleri ayıklanmış exclude listesi üretir."""
        if exclude_files is None:
            return []
        if isinstance(exclude_files, str):
            raw_items = exclude_files.split(",")
        else:
            raw_items = [str(item) for item in exclude_files]
        return [item.strip().lstrip("./") for item in raw_items if item and item.strip()]

    @staticmethod
    def _is_excluded_coverage_target(target_path: str, exclude_files: list[str]) -> bool:
        """Coverage hedefinin exclude kuralıyla eşleşip eşleşmediğini belirler."""
        normalized_target = str(target_path or "").strip().lstrip("./")
        if not normalized_target:
            return False
        target_parts = Path(normalized_target).parts
        for exclude_file in exclude_files:
            normalized_exclude = str(exclude_file or "").strip().lstrip("./")
            if not normalized_exclude:
                continue
            if normalized_target == normalized_exclude or normalized_target.endswith(
                f"/{normalized_exclude}"
            ):
                return True
            if "/" not in normalized_exclude and normalized_exclude in target_parts:
                return True
        return False

    @staticmethod
    def _cap_autonomous_finding_scope(
        finding: dict[str, Any],
        *,
        max_missing_lines: int = 25,
        max_missing_branches: int = 10,
    ) -> dict[str, Any]:
        """Otonom test üretiminde tek adayın bağlamını mikro kapsama dilimine indirger."""
        capped = dict(finding)
        line_limit = max(1, int(max_missing_lines or 25))
        branch_limit = max(1, int(max_missing_branches or 10))
        missing_lines = list(capped.get("missing_lines", []) or [])
        missing_branches = list(capped.get("missing_branches", []) or [])
        capped["missing_lines"] = missing_lines[:line_limit]
        capped["missing_branches"] = missing_branches[:branch_limit]
        if len(missing_lines) > line_limit or len(missing_branches) > branch_limit:
            capped["autonomous_scope_cap"] = {
                "max_missing_lines": line_limit,
                "max_missing_branches": branch_limit,
                "original_missing_lines": len(missing_lines),
                "original_missing_branches": len(missing_branches),
            }
            capped["summary"] = (
                f"{capped.get('summary', '')} "
                f"autonomous_scope_capped(lines={line_limit}/{len(missing_lines)}, "
                f"branches={branch_limit}/{len(missing_branches)})"
            ).strip()
        return capped

    def _resolve_repo_path(self, path_value: str) -> Path:
        """Repo base dizinine göre path çözer; mutlak pathleri olduğu gibi korur."""
        raw_path = Path(str(path_value or "").strip())
        if raw_path.is_absolute():
            return raw_path
        return Path(self.cfg.BASE_DIR) / raw_path

    def _validate_generated_test_before_write(
        self,
        *,
        suggested_test_path: str,
        generated_test: str,
        append: bool,
    ) -> tuple[bool, str, dict[str, Any]]:
        """Append öncesi sözdizimi ve test fonksiyonu çakışmalarını fail-closed kontrol eder."""
        details: dict[str, Any] = {"generated_test_functions": [], "existing_test_functions": []}
        if not str(suggested_test_path or "").strip():
            return False, "suggested_test_path boş olduğu için test yazımı engellendi.", details
        if not str(generated_test or "").strip():
            return False, "generated_test boş olduğu için test yazımı engellendi.", details

        try:
            generated_names = self._extract_test_function_names(generated_test)
        except SyntaxError as exc:
            return False, f"Üretilen test kodu geçerli Python AST değil: {exc}", details
        details["generated_test_functions"] = sorted(generated_names)

        if not generated_names:
            return (
                False,
                "Üretilen test kodunda test_ ile başlayan pytest fonksiyonu bulunamadı.",
                details,
            )
        if len(generated_names) != sum(
            1
            for node in ast.walk(ast.parse(generated_test))
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
            and node.name.startswith("test_")
        ):
            return False, "Üretilen test kodunda yinelenen test fonksiyon adı var.", details

        quality_rejection = self._candidate_rejection_reason(generated_test)
        details["quality_rejection_reason"] = quality_rejection
        if quality_rejection:
            return False, f"Üretilen test kalite kapısından geçemedi: {quality_rejection}", details

        if not append:
            return True, "AST kontrolü başarılı.", details

        target_path = self._resolve_repo_path(suggested_test_path)
        if not target_path.exists():
            return True, "AST kontrolü başarılı; hedef test dosyası yeni oluşturulacak.", details

        try:
            existing_text = target_path.read_text(encoding="utf-8")
            existing_names = self._extract_test_function_names(existing_text)
        except SyntaxError as exc:
            return False, f"Mevcut test dosyası AST olarak ayrıştırılamadı: {exc}", details
        except OSError as exc:
            return False, f"Mevcut test dosyası okunamadı: {exc}", details

        details["existing_test_functions"] = sorted(existing_names)
        collisions = sorted(generated_names & existing_names)
        if collisions:
            details["collisions"] = collisions
            return (
                False,
                "Test fonksiyonu adı çakışması nedeniyle append engellendi: "
                + ", ".join(collisions),
                details,
            )
        return True, "AST kontrolü başarılı; çakışma bulunmadı.", details

    @staticmethod
    def _parse_payload(raw: str) -> dict[str, Any]:
        text = (raw or "").strip()
        if not text:
            return {}
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            if re.match(r"^(pytest|python\s+-m\s+pytest)\b", text, re.IGNORECASE):
                return {"command": text}
            return {
                "instruction": text,
                "command": "pytest --cov=. --cov-report=xml --cov-report=term",
            }
        return parsed if isinstance(parsed, dict) else {"command": text}

    @staticmethod
    def _suggest_test_path(target_path: str) -> str:
        normalized = str(target_path or "").strip().lstrip("./")
        if not normalized:
            return "tests/test_generated.py"
        path_obj = Path(normalized)
        parent_dir = str(path_obj.parent).strip(".").strip("/")
        stem = path_obj.stem
        if parent_dir:
            return f"tests/{parent_dir}/test_{stem}.py"
        return f"tests/test_{stem}.py"

    @staticmethod
    def _module_import_path(target_path: str) -> str:
        normalized = str(target_path or "").strip().lstrip("./")
        if normalized.endswith(".py"):
            normalized = normalized[:-3]
        if normalized.endswith("/__init__"):
            normalized = normalized[: -len("/__init__")]
        return normalized.replace("/", ".") or "main"

    @staticmethod
    def _safe_test_name_fragment(target_path: str) -> str:
        module_path = CoverageAgent._module_import_path(target_path)
        safe = re.sub(r"[^0-9A-Za-z_]+", "_", module_path).strip("_")
        return safe or "generated"

    @staticmethod
    def _build_deterministic_test_template(*, finding: dict[str, Any], llm_idea: str = "") -> str:
        """Fail-closed placeholder used when LLM output is too weak to write safely.

        CoverageAgent must not inflate coverage by writing import-only or synthetic
        exception tests. Returning a non-test placeholder makes downstream quality
        gates reject the candidate deterministically instead of accepting a weak
        template.
        """
        target_path = str(finding.get("target_path", "") or "<unknown>")
        rejection = CoverageAgent._candidate_rejection_reason(str(llm_idea or ""), finding=finding)
        first_line = " ".join(str(llm_idea or "").strip().split())[:160]
        idea_comment = f" LLM idea: {first_line}" if first_line else ""
        return (
            f"# CoverageAgent blocked weak generated test for {target_path}."
            f" reason={rejection or 'quality_gate_failed'}.{idea_comment}\n"
        )

    @staticmethod
    def _clean_code_output(raw_output: str) -> str:
        """LLM çıktısından gelebilecek markdown kod çitlerini temizler."""
        clean_text = str(raw_output or "").strip()
        lines = clean_text.splitlines()
        blocks: list[tuple[str, str]] = []
        in_fence = False
        current_lang = ""
        current_code: list[str] = []

        for line in lines:
            marker = line.strip()
            if marker.startswith("```"):
                if not in_fence:
                    in_fence = True
                    current_lang = marker[3:].strip().lower()
                    current_code = []
                    continue
                blocks.append((current_lang, "\n".join(current_code).strip()))
                in_fence = False
                current_lang = ""
                current_code = []
                continue
            if in_fence:
                current_code.append(line)

        if blocks:
            python_blocks = [code for lang, code in blocks if lang == "python" and code]
            selected_blocks = python_blocks or [code for _, code in blocks if code]
            return "\n\n".join(selected_blocks).strip()

        if in_fence:
            return "\n".join(current_code).strip()

        return clean_text

    @staticmethod
    def _is_pytest_raises_call(node: ast.AST) -> bool:
        return (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "raises"
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "pytest"
        )

    @staticmethod
    def _is_tautological_mock_called_assertion(node: ast.AST) -> bool:
        return (
            isinstance(node, ast.Attribute)
            and node.attr == "called"
            and isinstance(node.value, ast.Name)
            and ("mock" in node.value.id.lower() or node.value.id.lower() in {"stub", "spy"})
        )

    @staticmethod
    def _has_runtime_behavior_signal(node: ast.AST) -> bool:
        for child in ast.walk(node):
            if isinstance(child, ast.Call):
                return True
            if isinstance(child, ast.Name) and child.id not in {"True", "False", "None"}:
                return True
            if isinstance(child, ast.Attribute):
                return True
            if isinstance(child, ast.Subscript):
                return True
        return False

    @staticmethod
    def _has_mock_call_verification(tree: ast.AST) -> bool:
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr.startswith("assert_")
                and "called" in node.func.attr
            ):
                return True
        return False

    @staticmethod
    def _uses_mocking(tree: ast.AST) -> bool:
        for node in ast.walk(tree):
            if isinstance(node, ast.Name) and node.id in {
                "Mock",
                "MagicMock",
                "AsyncMock",
                "patch",
            }:
                return True
            if isinstance(node, ast.Attribute) and node.attr in {
                "Mock",
                "MagicMock",
                "AsyncMock",
                "patch",
            }:
                return True
            if isinstance(node, ast.Name) and node.id == "mocker":
                return True
        return False

    @staticmethod
    def _uses_direct_mock_creation(tree: ast.AST) -> bool:
        forbidden_names = {"Mock", "MagicMock", "AsyncMock", "patch"}
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module == "unittest.mock":
                if any(alias.name in forbidden_names or alias.name == "*" for alias in node.names):
                    return True
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name) and node.func.id in forbidden_names:
                    return True
                if isinstance(node.func, ast.Attribute) and node.func.attr in forbidden_names:
                    return True
        return False

    @staticmethod
    def _finding_mentions_exception_path(finding: dict[str, Any] | None) -> bool:
        if not isinstance(finding, dict):
            return False
        searchable_parts = [
            finding.get("summary", ""),
            finding.get("missing_lines_hint", ""),
            finding.get("missing_hint", ""),
            " ".join(str(item) for item in finding.get("missing_branches", []) or []),
        ]
        haystack = " ".join(str(part or "") for part in searchable_parts).lower()
        return any(
            marker in haystack
            for marker in ("exception", "pytest.raises", "raise ", "raises", "except", "hata")
        )

    @staticmethod
    def _root_name(node: ast.AST) -> str:
        """Return the root ``Name`` for attribute/call/subscript chains."""
        current = node
        while isinstance(current, ast.Attribute | ast.Subscript | ast.Call):
            if isinstance(current, ast.Attribute):
                current = current.value
                continue
            if isinstance(current, ast.Subscript):
                current = current.value
                continue
            current = current.func
        return current.id if isinstance(current, ast.Name) else ""

    @staticmethod
    def _literal_string(node: ast.AST) -> str:
        return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else ""

    @classmethod
    def _collect_target_import_aliases(
        cls, tree: ast.AST, target_module: str
    ) -> tuple[set[str], set[str], set[str]]:
        """Collect target module aliases, imported symbols and target patch strings."""
        module_aliases: set[str] = set()
        imported_symbols: set[str] = set()
        patch_targets: set[str] = set()
        target_module = str(target_module or "").strip()
        if not target_module:
            return module_aliases, imported_symbols, patch_targets

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == target_module:
                        module_aliases.add(alias.asname or alias.name.split(".")[0])
            elif isinstance(node, ast.ImportFrom):
                module = "." * int(node.level or 0) + str(node.module or "")
                if module == target_module:
                    for alias in node.names:
                        if alias.name != "*":
                            imported_symbols.add(alias.asname or alias.name)
            elif isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
                call = node.value
                is_importlib = (
                    isinstance(call.func, ast.Attribute)
                    and call.func.attr == "import_module"
                    and isinstance(call.func.value, ast.Name)
                    and call.func.value.id == "importlib"
                )
                if (
                    is_importlib
                    and call.args
                    and cls._literal_string(call.args[0]) == target_module
                ):
                    for target in node.targets:
                        if isinstance(target, ast.Name):
                            module_aliases.add(target.id)
            elif isinstance(node, ast.Call):
                func_name = ""
                if isinstance(node.func, ast.Name):
                    func_name = node.func.id
                elif isinstance(node.func, ast.Attribute):
                    if (
                        node.func.attr == "object"
                        and isinstance(node.func.value, ast.Name)
                        and node.func.value.id == "patch"
                    ):
                        func_name = "patch.object"
                    else:
                        func_name = node.func.attr
                if func_name in {"patch", "patch.object"} and node.args:
                    patch_target = cls._literal_string(node.args[0])
                    if patch_target.startswith(f"{target_module}."):
                        patch_targets.add(patch_target)
        return module_aliases, imported_symbols, patch_targets

    @classmethod
    def _call_references_target(
        cls,
        call: ast.Call,
        *,
        module_aliases: set[str],
        imported_symbols: set[str],
    ) -> bool:
        root = cls._root_name(call.func)
        if root in module_aliases or root in imported_symbols:
            return True
        return any(
            isinstance(child, ast.Name) and child.id in module_aliases | imported_symbols
            for child in ast.walk(call)
        )

    @classmethod
    def _is_import_only_assertion(
        cls, node: ast.Assert, *, module_aliases: set[str], target_module: str
    ) -> bool:
        """Detect assertions that merely prove a module was imported."""
        test = node.test
        if isinstance(test, ast.Compare):
            compared_nodes = [test.left, *test.comparators]
            names = {item.id for item in compared_nodes if isinstance(item, ast.Name)}
            constants = {item.value for item in compared_nodes if isinstance(item, ast.Constant)}
            if names & module_aliases and (None in constants or target_module in constants):
                return True
            for item in compared_nodes:
                if (
                    isinstance(item, ast.Call)
                    and isinstance(item.func, ast.Name)
                    and item.func.id == "getattr"
                    and item.args
                    and isinstance(item.args[0], ast.Name)
                    and item.args[0].id in module_aliases
                ):
                    return True
        if isinstance(test, ast.Call):
            func_name = test.func.id if isinstance(test.func, ast.Name) else ""
            if func_name in {"hasattr", "getattr"} and test.args:
                first_arg = test.args[0]
                return isinstance(first_arg, ast.Name) and first_arg.id in module_aliases
        return False

    @classmethod
    def _target_behavior_quality_reason(cls, tree: ast.AST, target_path: str) -> str:
        """Fail-closed quality gate for coverage tests tied to a target module.

        A candidate must both execute target behavior and assert on a value derived
        from that target behavior. Import-only smoke tests and unrelated local
        computations are rejected because they can inflate coverage without proving
        behavior.
        """
        target_module = cls._module_import_path(target_path)
        module_aliases, imported_symbols, patch_targets = cls._collect_target_import_aliases(
            tree, target_module
        )
        if not module_aliases and not imported_symbols and not patch_targets:
            return "generated_candidate_no_target_behavior_reference"

        target_derived_names: set[str] = set()
        target_call_seen = False
        target_coupled_assertion = False
        target_coupled_raises = False
        import_only_assert_seen = False

        for test_node in (
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
            and node.name.startswith("test_")
        ):
            for child in ast.walk(test_node):
                if isinstance(child, ast.Assign):
                    value_has_target_call = any(
                        isinstance(item, ast.Call)
                        and cls._call_references_target(
                            item,
                            module_aliases=module_aliases,
                            imported_symbols=imported_symbols,
                        )
                        for item in ast.walk(child.value)
                    )
                    if value_has_target_call:
                        target_call_seen = True
                        for target in child.targets:
                            if isinstance(target, ast.Name):
                                target_derived_names.add(target.id)
                elif isinstance(child, ast.AnnAssign):
                    value = child.value
                    value_has_target_call = value is not None and any(
                        isinstance(item, ast.Call)
                        and cls._call_references_target(
                            item,
                            module_aliases=module_aliases,
                            imported_symbols=imported_symbols,
                        )
                        for item in ast.walk(value)
                    )
                    if value_has_target_call and isinstance(child.target, ast.Name):
                        target_call_seen = True
                        target_derived_names.add(child.target.id)
                elif isinstance(child, ast.Call) and cls._call_references_target(
                    child, module_aliases=module_aliases, imported_symbols=imported_symbols
                ):
                    target_call_seen = True
                elif isinstance(child, ast.Assert):
                    if cls._is_import_only_assertion(
                        child, module_aliases=module_aliases, target_module=target_module
                    ):
                        import_only_assert_seen = True
                        continue
                    direct_target_call = any(
                        isinstance(item, ast.Call)
                        and cls._call_references_target(
                            item,
                            module_aliases=module_aliases,
                            imported_symbols=imported_symbols,
                        )
                        for item in ast.walk(child.test)
                    )
                    derived_value_assert = any(
                        isinstance(item, ast.Name) and item.id in target_derived_names
                        for item in ast.walk(child.test)
                    )
                    mock_assert = any(
                        isinstance(item, ast.Call)
                        and isinstance(item.func, ast.Attribute)
                        and item.func.attr.startswith("assert_")
                        for item in ast.walk(child.test)
                    )
                    if (
                        direct_target_call
                        or derived_value_assert
                        or (patch_targets and mock_assert)
                    ):
                        target_coupled_assertion = True
                elif isinstance(child, ast.With | ast.AsyncWith):
                    if any(cls._is_pytest_raises_call(item.context_expr) for item in child.items):
                        target_coupled_raises = any(
                            isinstance(item, ast.Call)
                            and cls._call_references_target(
                                item,
                                module_aliases=module_aliases,
                                imported_symbols=imported_symbols,
                            )
                            for stmt in child.body
                            for item in ast.walk(stmt)
                        )

        if not target_call_seen:
            return "generated_candidate_import_only_contract"
        if import_only_assert_seen and not target_coupled_assertion and not target_coupled_raises:
            return "generated_candidate_import_only_contract"
        if not target_coupled_assertion and not target_coupled_raises:
            return "generated_candidate_uncoupled_assertion"
        return ""

    @staticmethod
    def _candidate_rejection_reason(
        generated_test: str, finding: dict[str, Any] | None = None
    ) -> str:
        """Otonom batch yazımı öncesi boş/trivial test adaylarını fail-closed reddeder."""
        source = str(generated_test or "").strip()
        if not source:
            return "generated_candidate_empty"
        try:
            tree = ast.parse(source or "\n")
        except SyntaxError:
            return "generated_candidate_invalid_python"

        test_nodes = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
            and node.name.startswith("test_")
        ]
        if not test_nodes:
            return "generated_candidate_missing_pytest_function"

        has_behavioral_assert = False
        has_pytest_raises = False
        has_tautological_mock_called_assertion = False
        for test_node in test_nodes:
            for child in ast.walk(test_node):
                if isinstance(child, ast.Assert):
                    if isinstance(child.test, ast.Constant) and child.test.value is True:
                        continue
                    if CoverageAgent._is_tautological_mock_called_assertion(child.test):
                        has_tautological_mock_called_assertion = True
                        continue
                    if CoverageAgent._has_runtime_behavior_signal(child.test):
                        has_behavioral_assert = True
                if CoverageAgent._is_pytest_raises_call(child):
                    has_pytest_raises = True

        if has_tautological_mock_called_assertion:
            return "generated_candidate_tautological_mock_assertion"
        if CoverageAgent._uses_direct_mock_creation(tree):
            return "generated_candidate_direct_mock_creation_instead_of_shared_fixture"
        if CoverageAgent._uses_mocking(tree) and not CoverageAgent._has_mock_call_verification(
            tree
        ):
            return "generated_candidate_mock_without_call_assertion"
        if CoverageAgent._finding_mentions_exception_path(finding) and not has_pytest_raises:
            return "generated_candidate_missing_pytest_raises_for_exception_path"
        if not has_behavioral_assert and not has_pytest_raises:
            return "generated_candidate_trivial_or_missing_assertion"

        target_path = str((finding or {}).get("target_path", "") or "").strip()
        if target_path:
            target_quality_reason = CoverageAgent._target_behavior_quality_reason(tree, target_path)
            if target_quality_reason:
                return target_quality_reason
        return ""

    @staticmethod
    def _normalize_analysis(raw: Any) -> dict[str, Any]:
        if not isinstance(raw, dict):
            return {"summary": "", "findings": []}
        findings = raw.get("findings")
        normalized_findings = [item for item in list(findings or []) if isinstance(item, dict)]
        return {
            **raw,
            "summary": str(raw.get("summary", "") or ""),
            "findings": normalized_findings,
        }

    @staticmethod
    def _read_coveragerc(coveragerc_path: str) -> dict[str, Any]:
        path = Path((coveragerc_path or ".coveragerc").strip() or ".coveragerc")
        if not path.exists():
            return {"path": str(path), "exists": False, "run": {}, "report": {}}

        parser = configparser.ConfigParser()
        parser.read(path, encoding="utf-8")
        run_cfg = dict(parser.items("run")) if parser.has_section("run") else {}
        report_cfg = dict(parser.items("report")) if parser.has_section("report") else {}
        return {"path": str(path), "exists": True, "run": run_cfg, "report": report_cfg}

    @staticmethod
    def _parse_coverage_xml(coverage_xml_path: str, *, limit: int = 25) -> dict[str, Any]:
        path = Path((coverage_xml_path or "coverage.xml").strip() or "coverage.xml")
        if not path.exists():
            return {
                "path": str(path),
                "exists": False,
                "summary": "coverage.xml bulunamadı.",
                "files": [],
                "findings": [],
            }

        try:
            root = ET.parse(path).getroot()
        except ET.ParseError:
            return {
                "path": str(path),
                "exists": True,
                "summary": "coverage.xml ayrıştırılamadı.",
                "files": [],
                "findings": [],
                "total_findings": 0,
            }
        findings: list[dict[str, Any]] = []
        files: list[dict[str, Any]] = []

        for class_el in root.findall(".//class"):
            filename = class_el.attrib.get("filename", "")
            if not filename:
                continue
            line_rate = float(class_el.attrib.get("line-rate", "0") or 0.0)
            branch_rate = float(class_el.attrib.get("branch-rate", "0") or 0.0)
            missed_lines: list[int] = []
            missed_branches: list[str] = []

            for line_el in class_el.findall("./lines/line"):
                number = int(line_el.attrib.get("number", "0") or 0)
                hits = int(line_el.attrib.get("hits", "0") or 0)
                if hits == 0 and number > 0:
                    missed_lines.append(number)
                if line_el.attrib.get("branch") == "true":
                    cond_cov = str(line_el.attrib.get("condition-coverage", "") or "")
                    if cond_cov and not cond_cov.startswith("100%"):
                        missed_branches.append(f"{number}:{cond_cov}")

            files.append(
                {
                    "path": filename,
                    "line_rate": round(line_rate * 100, 2),
                    "branch_rate": round(branch_rate * 100, 2),
                    "missing_lines_count": len(missed_lines),
                    "missing_branches_count": len(missed_branches),
                }
            )

            if missed_lines or missed_branches:
                findings.append(
                    {
                        "finding_type": "coverage_gap",
                        "target_path": filename,
                        "summary": (
                            f"line={round(line_rate * 100, 2)}% branch={round(branch_rate * 100, 2)}% "
                            f"missing_lines={len(missed_lines)} missing_branches={len(missed_branches)}"
                        ),
                        "missing_lines": missed_lines[:200],
                        "missing_branches": missed_branches[:200],
                        "suggested_test_path": CoverageAgent._suggest_test_path(filename),
                    }
                )

        findings.sort(
            key=lambda item: (
                -len(item.get("missing_lines", []) or []),
                -len(item.get("missing_branches", []) or []),
                item.get("target_path", ""),
            )
        )
        files_sorted = sorted(files, key=lambda x: (x["line_rate"], x["branch_rate"], x["path"]))
        trimmed = findings[: max(1, int(limit) if limit is not None else 25)]
        return {
            "path": str(path),
            "exists": True,
            "summary": f"{len(findings)} dosyada coverage açığı bulundu.",
            "files": files_sorted,
            "findings": trimmed,
            "total_findings": len(findings),
        }

    @staticmethod
    def _parse_terminal_coverage_output(raw_output: str, *, limit: int = 25) -> dict[str, Any]:
        text = str(raw_output or "")
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        if not lines:
            return {"summary": "Coverage terminal çıktısı boş.", "files": [], "findings": []}

        collected: list[dict[str, Any]] = []
        pattern = re.compile(
            r"^(?P<path>[^\s].*?\.py)\s+"
            r"(?P<stmts>\d+)\s+"
            r"(?P<miss>\d+)\s+"
            r"(?P<branch>\d+)\s+"
            r"(?P<brpart>\d+)\s+"
            r"(?P<cover>\d+)%"
            r"(?:\s+(?P<missing>.+))?$"
        )

        for line in lines:
            match = pattern.match(line)
            if not match:
                continue
            data = match.groupdict()
            path = str(data.get("path", "") or "").strip()
            if not path:
                continue
            miss = int(data.get("miss", "0") or 0)
            branch = int(data.get("branch", "0") or 0)
            brpart = int(data.get("brpart", "0") or 0)
            cover_pct = float(data.get("cover", "0") or 0)
            missing_hint = str(data.get("missing", "") or "").strip()
            collected.append(
                {
                    "path": path,
                    "line_rate": round(cover_pct, 2),
                    "branch_rate": round((branch - brpart) / branch * 100, 2)
                    if branch > 0
                    else 100.0,
                    "missing_lines_count": miss,
                    "missing_branches_count": brpart,
                    "missing_hint": missing_hint,
                }
            )

        if not collected:
            return {
                "summary": "Coverage terminal çıktısı ayrıştırılamadı.",
                "files": [],
                "findings": [],
            }

        collected_sorted = sorted(
            collected,
            key=lambda item: (
                item.get("line_rate", 0.0),
                -int(item.get("missing_lines_count", 0) or 0),
                -int(item.get("missing_branches_count", 0) or 0),
                str(item.get("path", "")),
            ),
        )
        findings = []
        for item in collected_sorted:
            if float(item.get("line_rate", 0.0) or 0.0) >= 100.0:
                continue
            findings.append(
                {
                    "finding_type": "terminal_coverage_gap",
                    "target_path": item.get("path", ""),
                    "summary": (
                        f"line={item.get('line_rate')}% missing_lines={item.get('missing_lines_count')} "
                        f"missing_branches={item.get('missing_branches_count')}"
                    ),
                    "missing_lines_hint": item.get("missing_hint", ""),
                    "suggested_test_path": CoverageAgent._suggest_test_path(
                        str(item.get("path", ""))
                    ),
                }
            )

        return {
            "summary": f"Terminal çıktısında {len(findings)} coverage açığı bulundu.",
            "files": collected_sorted,
            "findings": findings[: max(1, int(limit) if limit is not None else 25)],
            "total_findings": len(findings),
        }

    @staticmethod
    def _build_dynamic_pytest_prompt(
        *,
        finding: dict[str, Any],
        coveragerc: dict[str, Any],
        source_excerpt: str = "",
    ) -> str:
        target = str(finding.get("target_path", "") or "")
        missing_lines = (
            ", ".join(str(x) for x in (finding.get("missing_lines", []) or [])[:50]) or "-"
        )
        missing_branches = (
            ", ".join(str(x) for x in (finding.get("missing_branches", []) or [])[:50]) or "-"
        )
        omit_cfg = (
            coveragerc.get("report", {}).get("omit", "") if isinstance(coveragerc, dict) else ""
        )
        include_cfg = (
            coveragerc.get("run", {}).get("include", "") if isinstance(coveragerc, dict) else ""
        )
        source_block = (
            f"\n[KAYNAK DOSYA]\n{source_excerpt[:6000]}\n"
            if source_excerpt.strip()
            else "\n[KAYNAK DOSYA] kaynak okunamadı; boş\n"
        )
        return (
            f"Hedef dosya: {target}\n"
            f"Önerilen test dosyası: {CoverageAgent._suggest_test_path(target)}\n"
            f"Eksik satırlar: {missing_lines}\n"
            f"Eksik branch'ler: {missing_branches}\n"
            f".coveragerc include: {include_cfg or '-'}\n"
            f".coveragerc omit: {omit_cfg or '-'}\n"
            f"{source_block}\n"
            "Görev: pytest uyumlu, deterministik ve ağ erişimsiz testler üret.\n"
            "- 'assert True' veya tautolojik kontroller YASAK.\n"
            "- Her test fonksiyonu en az 1 anlamlı assertion içermeli.\n"
            "- Assertion, hedef modülden çağrılan fonksiyon/metot sonucuna bağlanmalı; "
            "sadece import, module is not None, __name__ veya ilgisiz lokal hesap kontrolü YASAK.\n"
            "- Dış servis/LLM/DB/event/agent bağımlılıklarında tests/conftest.py ortak fixture'larını kullan; "
            "unittest.mock ile yeni Mock/MagicMock/AsyncMock nesnesi üretme.\n"
            f"- {SHARED_TEST_FIXTURE_GUIDANCE}\n"
            "- Hem başarılı hem hata (exception/edge-case) akışları için test üret.\n"
            "- Eksik satır/branch'lere doğrudan tetikleyici çağrılar yaz.\n"
            "- Sadece Python test kodu döndür."
        )

    async def _tool_run_pytest(self, arg: str) -> str:
        payload = self._parse_payload(arg)
        default_cmd = "pytest --cov=. --cov-report=xml --cov-report=term"
        command = str(payload.get("command", default_cmd) or default_cmd).strip()
        cwd = str(payload.get("cwd", self.cfg.BASE_DIR) or self.cfg.BASE_DIR)
        result = await self._call_maybe_async(self.code.run_pytest_and_collect, command, cwd)
        return json.dumps(result, ensure_ascii=False)

    async def _tool_analyze_pytest_output(self, arg: str) -> str:
        payload = self._parse_payload(arg)
        output = str(payload.get("output", arg) or arg)
        analysis = await self._call_maybe_async(self.code.analyze_pytest_output, output)
        return json.dumps(analysis, ensure_ascii=False)

    async def _tool_analyze_coverage_report(self, arg: str) -> str:
        payload = self._parse_payload(arg)
        coverage_xml_path = str(payload.get("coverage_xml", "coverage.xml") or "coverage.xml")
        coveragerc_path = str(payload.get("coveragerc", ".coveragerc") or ".coveragerc")
        terminal_output = str(payload.get("coverage_output", "") or "")
        limit_val = payload.get("limit")
        limit = int(limit_val) if limit_val is not None else 25
        coverage_analysis = self._parse_coverage_xml(coverage_xml_path, limit=limit)
        terminal_analysis = self._parse_terminal_coverage_output(terminal_output, limit=limit)
        coveragerc = self._read_coveragerc(coveragerc_path)
        findings = list(coverage_analysis.get("findings", []) or [])
        if not findings:
            findings = list(terminal_analysis.get("findings", []) or [])
        return json.dumps(
            {
                "summary": coverage_analysis.get("summary", ""),
                "coverage_xml": coverage_analysis,
                "coverage_terminal": terminal_analysis,
                "coveragerc": coveragerc,
                "findings": findings,
            },
            ensure_ascii=False,
        )

    async def _tool_analyze_test_artifacts(self, arg: str) -> str:
        """Legacy uyumluluk: coverage/junit artefaktlarını coverage analizi formatına dönüştürür."""
        text = (arg or "").strip()
        if text.startswith(("{", "[")):
            payload = self._parse_payload(text)
            if "coverage_xml" not in payload:
                payload["coverage_xml"] = ""
        else:
            payload = {"coverage_xml": text}
        return await self._tool_analyze_coverage_report(json.dumps(payload, ensure_ascii=False))

    async def _generate_test_candidate(
        self, *, target_path: str, pytest_output: str, analysis: dict[str, Any]
    ) -> str:
        read_ok, source_excerpt = (
            await self._call_maybe_async(self.code.read_file, target_path)
            if target_path
            else (False, "")
        )
        prompt = (
            f"Hedef modül: {target_path or 'belirlenemedi'}\n"
            f"Önerilen test yolu: {self._suggest_test_path(target_path)}\n"
            f"Pytest özeti: {analysis.get('summary', '')}\n"
            f"Bulgular: {json.dumps(analysis.get('findings', []), ensure_ascii=False)}\n\n"
            f"[PYTEST OUTPUT]\n{pytest_output[:4000]}\n\n"
            f"[KAYNAK DOSYA]\n{source_excerpt[:4000] if read_ok else 'kaynak okunamadı'}"
        )
        return await self.call_llm(
            [{"role": "user", "content": prompt}],
            system_prompt=self.TEST_GENERATION_PROMPT,
            temperature=0.1,
        )

    async def _tool_generate_missing_tests(self, arg: str) -> str:
        payload = self._parse_payload(arg)
        target_path = str(payload.get("target_path", "") or "")
        pytest_output = str(payload.get("pytest_output", "") or "")
        analysis = payload.get("analysis")
        coverage_finding = (
            payload.get("coverage_finding")
            if isinstance(payload.get("coverage_finding"), dict)
            else None
        )
        coveragerc_raw = payload.get("coveragerc")
        coveragerc: dict[str, Any] = coveragerc_raw if isinstance(coveragerc_raw, dict) else {}
        if coverage_finding and not target_path:
            target_path = str(coverage_finding.get("target_path", "") or "")
        if coverage_finding:
            source_excerpt = ""
            if target_path:
                read_ok, source_text = await self._call_maybe_async(
                    self.code.read_file, target_path
                )
                if read_ok:
                    source_excerpt = str(source_text or "")
            payload_prompt = self._build_dynamic_pytest_prompt(
                finding=coverage_finding,
                coveragerc=coveragerc,
                source_excerpt=source_excerpt,
            )
            llm_candidate_or_idea = await self.call_llm(
                [{"role": "user", "content": payload_prompt}],
                system_prompt=self.TEST_GENERATION_PROMPT,
                temperature=0.1,
            )
            cleaned_candidate = self._clean_code_output(str(llm_candidate_or_idea or ""))
            if self._candidate_rejection_reason(cleaned_candidate, finding=coverage_finding):
                return self._build_deterministic_test_template(
                    finding=coverage_finding,
                    llm_idea=str(llm_candidate_or_idea or ""),
                )
            return cleaned_candidate
        if not isinstance(analysis, dict):
            analysis = await self._call_maybe_async(self.code.analyze_pytest_output, pytest_output)
        return await self._generate_test_candidate(
            target_path=target_path, pytest_output=pytest_output, analysis=analysis
        )

    async def _tool_write_missing_tests(self, arg: str) -> str:
        payload = self._parse_payload(arg)
        suggested_test_path = str(payload.get("suggested_test_path", "") or "")
        generated_test = self._clean_code_output(str(payload.get("generated_test", "") or ""))
        append = bool(payload.get("append", True))
        validation_ok, validation_message, validation_details = (
            self._validate_generated_test_before_write(
                suggested_test_path=suggested_test_path,
                generated_test=generated_test,
                append=append,
            )
        )
        if not validation_ok:
            return json.dumps(
                {
                    "success": False,
                    "suggested_test_path": suggested_test_path,
                    "message": validation_message,
                    "validation": validation_details,
                },
                ensure_ascii=False,
            )

        ok, message = await self._call_maybe_async(
            self.code.write_generated_test,
            suggested_test_path,
            generated_test,
            append=append,
        )
        return json.dumps(
            {
                "success": ok,
                "suggested_test_path": suggested_test_path,
                "message": message,
                "validation": {"message": validation_message, **validation_details},
            },
            ensure_ascii=False,
        )

    async def _validate_candidate_with_isolated_pytest(
        self, *, suggested_test_path: str, generated_test: str
    ) -> tuple[bool, str, dict[str, Any]]:
        """Aday testi geçici dosyada `uv run pytest <test_file>` ile izole doğrular."""
        base_dir = Path(self.cfg.BASE_DIR)
        validation_dir = base_dir / "artifacts" / "coverage_candidate_validation"
        digest = hashlib.sha256(generated_test.encode("utf-8", errors="ignore")).hexdigest()[:12]
        stem = Path(suggested_test_path or "generated_candidate.py").stem or "generated_candidate"
        candidate_path = validation_dir / f"{stem}_{digest}.py"
        details: dict[str, Any] = {
            "isolated_test_file": str(candidate_path),
            "isolated_pytest_command": "",
        }
        try:
            validation_dir.mkdir(parents=True, exist_ok=True)
            candidate_path.write_text(generated_test, encoding="utf-8")
            try:
                command_path = candidate_path.relative_to(base_dir)
            except ValueError:
                command_path = candidate_path
            command = f"uv run pytest -q {shlex.quote(str(command_path))}"
            details["isolated_pytest_command"] = command
            result = await self._call_maybe_async(
                self.code.run_pytest_and_collect,
                command,
                str(base_dir),
            )
        except Exception as exc:  # noqa: BLE001 - doğrulama fail-closed olmalı.
            details["error"] = str(exc)
            return False, "generated_candidate_isolated_pytest_error", details
        finally:
            with contextlib.suppress(OSError):
                candidate_path.unlink()

        if not isinstance(result, dict):
            details["result_type"] = type(result).__name__
            return False, "generated_candidate_isolated_pytest_invalid_result", details
        analysis = result.get("analysis") if isinstance(result.get("analysis"), dict) else {}
        has_failures = (
            bool(analysis.get("has_failures", False)) if isinstance(analysis, dict) else False
        )
        success = bool(result.get("success", not has_failures))
        details["result"] = {
            "success": success,
            "command": str(result.get("command", "") or ""),
            "output_excerpt": str(result.get("output", "") or "")[:1000],
        }
        if not success or has_failures:
            return False, "generated_candidate_isolated_pytest_failed", details
        return True, "isolated_pytest_passed", details

    async def run_autonomous_coverage_batch(
        self,
        *,
        coverage_xml: str = "coverage.xml",
        coveragerc: str = ".coveragerc",
        limit: int = 3,
        batch_size: int = 1,
        append: bool = True,
        reviewer_gate: Callable[[str, dict[str, Any]], Awaitable[bool]] | None = None,
        max_missing_lines_per_finding: int = 25,
        max_missing_branches_per_finding: int = 10,
        exclude_files: list[str] | str | None = None,
    ) -> dict[str, Any]:
        """Coverage bulgularını mikro batch kuyruğunda üretip write_missing_tests ile yazar."""
        analysis_raw = await self._tool_analyze_coverage_report(
            json.dumps(
                {"coverage_xml": coverage_xml, "coveragerc": coveragerc, "limit": limit},
                ensure_ascii=False,
            )
        )
        analysis = json.loads(analysis_raw)
        findings = [
            item for item in list(analysis.get("findings", []) or []) if isinstance(item, dict)
        ]
        original_findings_count = len(findings)
        normalized_exclude_files = self._normalize_exclude_files(exclude_files)
        excluded_findings: list[dict[str, Any]] = []
        if normalized_exclude_files:
            actionable_findings: list[dict[str, Any]] = []
            for finding in findings:
                target_path = str(finding.get("target_path", "") or "")
                if self._is_excluded_coverage_target(target_path, normalized_exclude_files):
                    excluded_findings.append(
                        {
                            "target_path": target_path,
                            "suggested_test_path": str(
                                finding.get("suggested_test_path", "") or ""
                            ),
                        }
                    )
                    logging.info(
                        "[CoverageAgent] Coverage hedefi exclude listesinde olduğu için "
                        "otonom kuyruktan çıkarıldı: %s",
                        target_path,
                    )
                    continue
                actionable_findings.append(finding)
            findings = actionable_findings
        batches = self._build_finding_batches(findings, batch_size=batch_size, max_findings=limit)
        results: list[dict[str, Any]] = []

        for batch_index, batch in enumerate(batches, start=1):
            for finding_index, finding in enumerate(batch, start=1):
                suggested_test_path = str(
                    finding.get("suggested_test_path")
                    or self._suggest_test_path(str(finding.get("target_path", "") or ""))
                )
                scoped_finding = self._cap_autonomous_finding_scope(
                    finding,
                    max_missing_lines=max_missing_lines_per_finding,
                    max_missing_branches=max_missing_branches_per_finding,
                )
                generated = await self._tool_generate_missing_tests(
                    json.dumps(
                        {
                            "coverage_finding": scoped_finding,
                            "coveragerc": analysis.get("coveragerc", {}),
                        },
                        ensure_ascii=False,
                    )
                )
                generated = self._clean_code_output(generated)
                candidate_rejection_reason = self._candidate_rejection_reason(
                    generated, finding=finding
                )
                if candidate_rejection_reason:
                    results.append(
                        {
                            "success": False,
                            "status": "review_rejected",
                            "batch_index": batch_index,
                            "finding_index": finding_index,
                            "target_path": finding.get("target_path", ""),
                            "suggested_test_path": suggested_test_path,
                            "review_reason": candidate_rejection_reason,
                            "generated_test_candidate": generated,
                        }
                    )
                    continue

                (
                    isolated_ok,
                    isolated_reason,
                    isolated_details,
                ) = await self._validate_candidate_with_isolated_pytest(
                    suggested_test_path=suggested_test_path,
                    generated_test=generated,
                )
                if not isolated_ok:
                    results.append(
                        {
                            "success": False,
                            "status": "review_rejected",
                            "batch_index": batch_index,
                            "finding_index": finding_index,
                            "target_path": finding.get("target_path", ""),
                            "suggested_test_path": suggested_test_path,
                            "review_reason": isolated_reason,
                            "generated_test_candidate": generated,
                            "validation": isolated_details,
                        }
                    )
                    continue

                approved = True
                review_reason = "reviewer_gate_not_configured"
                review_error = ""
                if reviewer_gate is not None:
                    gate_finding = {
                        **finding,
                        "batch_index": batch_index,
                        "finding_index": finding_index,
                        "suggested_test_path": suggested_test_path,
                    }
                    try:
                        approved = bool(await reviewer_gate(generated, gate_finding))
                    except Exception as exc:  # noqa: BLE001 - reviewer gate hata verirse yazma fail-closed olmalı.
                        approved = False
                        review_reason = f"reviewer_gate_exception:{exc.__class__.__name__}"
                        review_error = str(exc)
                    else:
                        review_reason = "approved" if approved else "rejected"
                if not approved:
                    rejected_result = {
                        "success": False,
                        "status": "review_rejected",
                        "batch_index": batch_index,
                        "finding_index": finding_index,
                        "target_path": finding.get("target_path", ""),
                        "suggested_test_path": suggested_test_path,
                        "review_reason": review_reason,
                        "generated_test_candidate": generated,
                    }
                    if review_error:
                        rejected_result["review_error"] = review_error
                    results.append(rejected_result)
                    continue

                write_raw = await self._tool_write_missing_tests(
                    json.dumps(
                        {
                            "suggested_test_path": suggested_test_path,
                            "generated_test": generated,
                            "append": append,
                        },
                        ensure_ascii=False,
                    )
                )
                write_result = json.loads(write_raw)
                results.append(
                    {
                        "success": bool(write_result.get("success", False)),
                        "status": "tests_written"
                        if write_result.get("success")
                        else "write_failed",
                        "batch_index": batch_index,
                        "finding_index": finding_index,
                        "target_path": finding.get("target_path", ""),
                        "suggested_test_path": suggested_test_path,
                        "write_result": write_result,
                    }
                )

        status = "batch_completed"
        if not findings:
            status = "no_actionable_findings" if excluded_findings else "no_gaps_detected"

        return {
            "success": any(item.get("success") for item in results) if results else True,
            "status": status,
            "summary": analysis.get("summary", ""),
            "total_findings": len(findings),
            "original_total_findings": original_findings_count,
            "excluded_findings_count": len(excluded_findings),
            "excluded_findings": excluded_findings,
            "exclude_files": normalized_exclude_files,
            "batch_count": len(batches),
            "results": results,
        }

    async def _tool_autonomous_batch_heal(self, arg: str) -> str:
        payload = self._parse_payload(arg)
        exclude_files = self._normalize_exclude_files(
            payload.get("exclude_files") if "exclude_files" in payload else None
        )
        result = await self.run_autonomous_coverage_batch(
            coverage_xml=str(payload.get("coverage_xml", "coverage.xml") or "coverage.xml"),
            coveragerc=str(payload.get("coveragerc", ".coveragerc") or ".coveragerc"),
            limit=int(payload.get("limit", 3) or 3),
            batch_size=int(payload.get("batch_size", 1) or 1),
            append=bool(payload.get("append", True)),
            max_missing_lines_per_finding=int(
                payload.get("max_missing_lines_per_finding", 25) or 25
            ),
            max_missing_branches_per_finding=int(
                payload.get("max_missing_branches_per_finding", 10) or 10
            ),
            exclude_files=exclude_files,
        )
        return json.dumps(result, ensure_ascii=False)

    async def _record_task(
        self,
        *,
        command: str,
        pytest_output: str,
        analysis: dict[str, Any],
        generated_test: str,
        review_payload: dict[str, Any],
        status: str,
    ) -> None:
        db = await self._ensure_db()
        task = await db.create_coverage_task(
            tenant_id="default",
            requester_role=self.role_name,
            command=command,
            pytest_output=pytest_output,
            status=status,
            target_path=str(review_payload.get("target_path", "") or ""),
            suggested_test_path=str(review_payload.get("suggested_test_path", "") or ""),
            review_payload_json=json.dumps(review_payload, ensure_ascii=False),
        )
        for finding in list(analysis.get("findings", []) or []):
            await db.add_coverage_finding(
                task_id=task.id,
                finding_type=str(finding.get("finding_type", "unknown") or "unknown"),
                target_path=str(finding.get("target_path", "") or ""),
                summary=str(finding.get("summary", "") or ""),
                severity="medium",
                details=dict(finding),
            )

    async def run_task(self, task_prompt: str) -> Any:
        prompt = (task_prompt or "").strip()
        if not prompt:
            return "[UYARI] Boş coverage görevi verildi."

        lower = prompt.lower()
        if lower.startswith("run_pytest|"):
            return await self.call_tool("run_pytest", prompt.split("|", 1)[1].strip())
        if lower.startswith("analyze_pytest_output|"):
            return await self.call_tool("analyze_pytest_output", prompt.split("|", 1)[1].strip())
        if lower.startswith("analyze_coverage_report|"):
            return await self.call_tool("analyze_coverage_report", prompt.split("|", 1)[1].strip())
        if lower.startswith("analyze_test_artifacts|"):
            return await self.call_tool("analyze_test_artifacts", prompt.split("|", 1)[1].strip())
        if lower.startswith("generate_missing_tests|"):
            return await self.call_tool("generate_missing_tests", prompt.split("|", 1)[1].strip())
        if lower.startswith("write_missing_tests|"):
            return await self.call_tool("write_missing_tests", prompt.split("|", 1)[1].strip())
        if lower.startswith("autonomous_batch_heal|"):
            return await self.call_tool("autonomous_batch_heal", prompt.split("|", 1)[1].strip())

        payload = self._parse_payload(prompt)
        default_cmd = "pytest --cov=. --cov-report=xml --cov-report=term"
        command = str(payload.get("command", default_cmd) or default_cmd).strip()
        cwd = str(payload.get("cwd", self.cfg.BASE_DIR) or self.cfg.BASE_DIR)
        pytest_result = await self._call_maybe_async(self.code.run_pytest_and_collect, command, cwd)
        analysis = self._normalize_analysis(pytest_result.get("analysis"))
        findings = list(analysis.get("findings") or [])
        if not findings:
            return json.dumps(
                {
                    "success": True,
                    "status": "no_gaps_detected",
                    "command": command,
                    "summary": analysis.get("summary", ""),
                },
                ensure_ascii=False,
            )

        primary = findings[0]
        target_path = str(primary.get("target_path", "") or "")
        suggested_test_path = self._suggest_test_path(target_path)
        generated_test = await self._generate_test_candidate(
            target_path=target_path,
            pytest_output=str(pytest_result.get("output", "") or ""),
            analysis=analysis,
        )
        generated_test = self._clean_code_output(generated_test)
        review_payload = {
            "review_context": (
                f"[COVERAGE AGENT]\ncommand={command}\n"
                f"suggested_test_path={suggested_test_path}\n"
                f"target_path={target_path}\n"
                f"analysis={json.dumps(analysis, ensure_ascii=False)}\n\n"
                f"[GENERATED_TEST_CANDIDATE]\n{generated_test}"
            ),
            "generated_test_candidate": generated_test,
            "suggested_test_path": suggested_test_path,
            "target_path": target_path,
            "pytest_output": str(pytest_result.get("output", "") or "")[:4000],
            "is_approved": False,
            "approval_status": "pending_reviewer_or_human",
        }
        candidate_rejection_reason = self._candidate_rejection_reason(
            generated_test, finding=primary
        )
        if candidate_rejection_reason:
            write_result = {
                "success": False,
                "suggested_test_path": suggested_test_path,
                "message": f"Üretilen test kalite kapısından geçemedi: {candidate_rejection_reason}",
                "validation": {"quality_rejection_reason": candidate_rejection_reason},
            }
        else:
            write_result = json.loads(
                await self._tool_write_missing_tests(
                    json.dumps(
                        {
                            "suggested_test_path": suggested_test_path,
                            "generated_test": generated_test,
                            "append": True,
                        },
                        ensure_ascii=False,
                    )
                )
            )
        write_ok = bool(write_result.get("success", False))
        write_message = str(write_result.get("message", "") or "")
        review_payload["write_result"] = write_result
        try:
            await self._record_task(
                command=command,
                pytest_output=str(pytest_result.get("output", "") or ""),
                analysis=analysis,
                generated_test=generated_test,
                review_payload=review_payload,
                status="tests_written" if write_ok else "write_failed",
            )
        except Exception as exc:
            logging.exception("[CoverageAgent] Görev kaydedilirken hata oluştu: %s", exc)
        return json.dumps(
            {
                "success": write_ok,
                "status": "tests_written" if write_ok else "write_failed",
                "command": command,
                "target_path": target_path,
                "suggested_test_path": suggested_test_path,
                "analysis": analysis,
                "generated_test_candidate": generated_test,
                "is_approved": False,
                "approval_status": "pending_reviewer_or_human",
                "write_message": write_message,
            },
            ensure_ascii=False,
        )
