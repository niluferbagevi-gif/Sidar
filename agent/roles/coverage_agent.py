"""Coverage açığını kapatmak için otonom test üretimi yapan ajan."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, Optional

from config import Config

from agent.base_agent import BaseAgent


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

    def __init__(self, cfg: Optional[Config] = None) -> None:
        super().__init__(cfg=cfg, role_name="coverage")
        from managers.code_manager import CodeManager
        from managers.security import SecurityManager

        self.security = SecurityManager(cfg=self.cfg)
        self.code = CodeManager(self.security, base_dir=self.cfg.BASE_DIR)
        self._db = None
        self._db_lock: asyncio.Lock | None = None
        self.register_tool("run_pytest", self._tool_run_pytest)
        self.register_tool("analyze_pytest_output", self._tool_analyze_pytest_output)
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
    def _parse_payload(raw: str) -> dict[str, Any]:
        text = (raw or "").strip()
        if not text:
            return {}
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            return {"command": text}
        return parsed if isinstance(parsed, dict) else {"command": text}

    @staticmethod
    def _suggest_test_path(target_path: str) -> str:
        normalized = str(target_path or "").strip().lstrip("./")
        if not normalized:
            return "tests/test_generated_coverage_agent.py"
        stem = Path(normalized).stem
        return f"tests/test_{stem}_coverage.py"

    async def _tool_run_pytest(self, arg: str) -> str:
        payload = self._parse_payload(arg)
        command = str(payload.get("command", "pytest -q") or "pytest -q").strip()
        cwd = str(payload.get("cwd", self.cfg.BASE_DIR) or self.cfg.BASE_DIR)
        result = await asyncio.to_thread(self.code.run_pytest_and_collect, command, cwd)
        return json.dumps(result, ensure_ascii=False)

    async def _tool_analyze_pytest_output(self, arg: str) -> str:
        payload = self._parse_payload(arg)
        output = str(payload.get("output", arg) or arg)
        analysis = await asyncio.to_thread(self.code.analyze_pytest_output, output)
        return json.dumps(analysis, ensure_ascii=False)

    async def _generate_test_candidate(self, *, target_path: str, pytest_output: str, analysis: dict[str, Any]) -> str:
        read_ok, source_excerpt = await asyncio.to_thread(self.code.read_file, target_path) if target_path else (False, "")
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
        if not isinstance(analysis, dict):
            analysis = await asyncio.to_thread(self.code.analyze_pytest_output, pytest_output)
        return await self._generate_test_candidate(target_path=target_path, pytest_output=pytest_output, analysis=analysis)

    async def _tool_write_missing_tests(self, arg: str) -> str:
        payload = self._parse_payload(arg)
        suggested_test_path = str(payload.get("suggested_test_path", "") or "")
        generated_test = str(payload.get("generated_test", "") or "")
        append = bool(payload.get("append", True))
        ok, message = await asyncio.to_thread(
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
        if lower.startswith("generate_missing_tests|"):
            return await self.call_tool("generate_missing_tests", prompt.split("|", 1)[1].strip())
        if lower.startswith("write_missing_tests|"):
            return await self.call_tool("write_missing_tests", prompt.split("|", 1)[1].strip())

        payload = self._parse_payload(prompt)
        command = str(payload.get("command", "pytest -q") or "pytest -q").strip()
        cwd = str(payload.get("cwd", self.cfg.BASE_DIR) or self.cfg.BASE_DIR)
        pytest_result = await asyncio.to_thread(self.code.run_pytest_and_collect, command, cwd)
        analysis = dict(pytest_result.get("analysis") or {})
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
        }
        write_ok, write_message = await asyncio.to_thread(
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
        except Exception:
            pass
        return json.dumps(
            {
                "success": write_ok,
                "status": "tests_written" if write_ok else "write_failed",
                "command": command,
                "target_path": target_path,
                "suggested_test_path": suggested_test_path,
                "analysis": analysis,
                "generated_test_candidate": generated_test,
                "write_message": write_message,
            },
            ensure_ascii=False,
        )