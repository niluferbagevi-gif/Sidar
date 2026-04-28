"""Coverage açığını kapatmak için otonom test üretimi yapan ajan."""

from __future__ import annotations

import asyncio
import configparser
import inspect
import json
import logging
import re
import xml.etree.ElementTree as ET
from collections.abc import Callable
from pathlib import Path
from typing import Any

from agent.base_agent import BaseAgent
from agent.registry import AgentCatalog
from config import Config


@AgentCatalog.register(
    capabilities=["coverage_analysis", "pytest_output_analysis", "autonomous_test_generation"],
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
        self._db = None
        self._db_lock: asyncio.Lock | None = None
        self.register_tool("run_pytest", self._tool_run_pytest)
        self.register_tool("analyze_pytest_output", self._tool_analyze_pytest_output)
        self.register_tool("analyze_coverage_report", self._tool_analyze_coverage_report)
        self.register_tool("generate_missing_tests", self._tool_generate_missing_tests)
        self.register_tool("write_missing_tests", self._tool_write_missing_tests)

    async def _ensure_db(self):
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
    async def _call_maybe_async(
        func: Callable[..., Any], *args: Any, **kwargs: Any
    ) -> Any:
        """Hem senkron hem async tool yardımcılarını güvenli şekilde çalıştır."""
        result = func(*args, **kwargs)
        if inspect.isawaitable(result):
            return await result
        return result

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
    def _build_dynamic_pytest_prompt(*, finding: dict[str, Any], coveragerc: dict[str, Any]) -> str:
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
        return (
            f"Hedef dosya: {target}\n"
            f"Önerilen test dosyası: {CoverageAgent._suggest_test_path(target)}\n"
            f"Eksik satırlar: {missing_lines}\n"
            f"Eksik branch'ler: {missing_branches}\n"
            f".coveragerc include: {include_cfg or '-'}\n"
            f".coveragerc omit: {omit_cfg or '-'}\n\n"
            "Görev: pytest uyumlu, deterministik ve ağ erişimsiz testler üret.\n"
            "- Dış servis çağrılarını unittest.mock ile taklit et.\n"
            "- Gerekirse fixture kullan.\n"
            "- Hem başarılı (200) hem hata (404/500) akışları için test üret.\n"
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
        coveragerc = (
            payload.get("coveragerc") if isinstance(payload.get("coveragerc"), dict) else {}
        )
        if coverage_finding and not target_path:
            target_path = str(coverage_finding.get("target_path", "") or "")
        if coverage_finding:
            payload_prompt = self._build_dynamic_pytest_prompt(
                finding=coverage_finding, coveragerc=coveragerc
            )
            return await self.call_llm(
                [{"role": "user", "content": payload_prompt}],
                system_prompt=self.TEST_GENERATION_PROMPT,
                temperature=0.1,
            )
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
            },
            ensure_ascii=False,
        )

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

    async def run_task(self, task_prompt: str):
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
        if lower.startswith("generate_missing_tests|"):
            return await self.call_tool("generate_missing_tests", prompt.split("|", 1)[1].strip())
        if lower.startswith("write_missing_tests|"):
            return await self.call_tool("write_missing_tests", prompt.split("|", 1)[1].strip())

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
        write_ok, write_message = await self._call_maybe_async(
            self.code.write_generated_test,
            suggested_test_path,
            generated_test,
            append=True,
        )
        review_payload["write_result"] = {
            "success": write_ok,
            "message": write_message,
        }
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
