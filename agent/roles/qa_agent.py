"""Coverage ve test otomasyonu odaklı QA ajanı."""

from __future__ import annotations

import asyncio
import configparser
import json
import re
from pathlib import Path
from typing import Any

from agent.base_agent import BaseAgent
from agent.registry import AgentCatalog
from config import Config
from core.ci_remediation import build_ci_remediation_payload
from managers.code_manager import CodeManager
from managers.security import SecurityManager


@AgentCatalog.register(capabilities=["test_generation", "ci_remediation"], is_builtin=True)
class QAAgent(BaseAgent):
    """Coverage açığını analiz edip pytest tabanlı test taslağı üreten uzman ajan."""

    SYSTEM_PROMPT = (
        "Sen coverage ve test otomasyonu odaklı bir QA ajansın. "
        "Eksik test alanlarını belirler, .coveragerc hedeflerini dikkate alır ve "
        "CI remediation bağlamını kullanarak tests/ altında deterministik pytest çıktıları üretirsin."
    )

    TEST_GENERATION_PROMPT = (
        "Sen kıdemli bir Python test mühendisisin. Yalnızca çalıştırılabilir pytest kodu üret. "
        "Ağ erişimi, rastgelelik ve dış servis bağımlılıkları kullanma. "
        "Yanıtında markdown çiti veya açıklama olmasın."
    )

    def __init__(
        self,
        cfg: Config | None = None,
        *,
        config: Config | None = None,
    ) -> None:
        resolved_cfg = cfg or config
        super().__init__(cfg=resolved_cfg, role_name="qa")
        self.security = SecurityManager(cfg=self.cfg)
        self.code = CodeManager(self.security, base_dir=self.cfg.BASE_DIR)
        self.register_tool("read_file", self._tool_read_file)
        self.register_tool("list_directory", self._tool_list_directory)
        self.register_tool("grep_search", self._tool_grep_search)
        self.register_tool("coverage_config", self._tool_coverage_config)
        self.register_tool("ci_remediation", self._tool_ci_remediation)
        self.register_tool("write_file", self._tool_write_file)
        self.register_tool("run_pytest", self._tool_run_pytest)

    async def _tool_read_file(self, arg: str) -> str:
        _ok, out = await asyncio.to_thread(self.code.read_file, arg)
        return out

    async def _tool_list_directory(self, arg: str) -> str:
        _ok, out = await asyncio.to_thread(self.code.list_directory, arg or ".")
        return out

    async def _tool_grep_search(self, arg: str) -> str:
        parts = arg.split("|||", 3)
        pattern = parts[0].strip() if parts else ""
        path = parts[1].strip() if len(parts) > 1 else "."
        file_glob = parts[2].strip() if len(parts) > 2 else "*"
        context_lines = (
            int(parts[3].strip()) if len(parts) > 3 and parts[3].strip().isdigit() else 2
        )
        _ok, out = await asyncio.to_thread(
            self.code.grep_files, pattern, path, file_glob, True, context_lines
        )
        return out

    def _coverage_config_summary(self) -> dict[str, Any]:
        parser = configparser.ConfigParser()
        coveragerc_path = Path(self.cfg.BASE_DIR) / ".coveragerc"
        parser.read(coveragerc_path, encoding="utf-8")
        omit_raw = parser.get("run", "omit", fallback="")
        omit = [part.strip() for part in re.split(r"[\n,]", omit_raw) if part.strip()]
        return {
            "path": str(coveragerc_path),
            "exists": coveragerc_path.exists(),
            "fail_under": parser.getint("report", "fail_under", fallback=0),
            "show_missing": parser.getboolean("report", "show_missing", fallback=False),
            "skip_covered": parser.getboolean("report", "skip_covered", fallback=False),
            "omit": omit,
        }

    async def _tool_coverage_config(self, _arg: str) -> str:
        return json.dumps(self._coverage_config_summary(), ensure_ascii=False)

    @staticmethod
    def _parse_json_payload(raw: str) -> dict[str, Any]:
        text = (raw or "").strip()
        if not text:
            return {}
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            return {"failure_summary": text}
        return parsed if isinstance(parsed, dict) else {"failure_summary": text}

    async def _tool_ci_remediation(self, arg: str) -> str:
        payload = self._parse_json_payload(arg)
        diagnosis = str(
            payload.pop(
                "diagnosis",
                "Coverage açığı ve eksik testler için QA remediation planı hazırlanıyor.",
            )
        ).strip()
        remediation = build_ci_remediation_payload(payload, diagnosis)
        return json.dumps(remediation, ensure_ascii=False)

    @staticmethod
    def _suggest_test_path(target_path: str) -> str:
        normalized = str(target_path or "").strip().lstrip("./")
        if not normalized:
            return "tests/test_generated_coverage.py"

        path_obj = Path(normalized)
        stem = path_obj.stem
        parent_dir = str(path_obj.parent).strip(".").strip("/")
        if parent_dir:
            return f"tests/{parent_dir}/test_{stem}.py"
        return f"tests/test_{stem}.py"

    @staticmethod
    def _sanitize_llm_code(raw_output: str) -> str:
        clean_text = str(raw_output or "").strip()
        if not clean_text.startswith("```"):
            return clean_text

        # We only enter this block when the response starts with a fence marker,
        # so drop the first line unconditionally and then remove an optional
        # trailing fence.
        lines = clean_text.splitlines()[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        return "\n".join(lines).strip()

    async def _generate_test_code(self, target_path: str, context: str) -> str:
        coverage = self._coverage_config_summary()
        prompt = (
            f"Hedef modül: {target_path}\n"
            f"Önerilen test dosyası: {self._suggest_test_path(target_path)}\n"
            f"Coverage fail_under: {coverage['fail_under']}\n"
            f"Coverage omit: {', '.join(coverage['omit']) or '-'}\n\n"
            "Aşağıdaki bağlama göre eksik senaryoları kapsayan pytest testleri yaz.\n"
            f"[BAGLAM]\n{context.strip()}"
        )
        raw_output = await self.call_llm(
            [{"role": "user", "content": prompt}],
            system_prompt=self.TEST_GENERATION_PROMPT,
            temperature=0.1,
        )
        return self._sanitize_llm_code(raw_output)

    async def _tool_write_file(self, arg: str) -> str:
        payload = self._parse_json_payload(arg)
        path = str(payload.get("path", "")).strip()
        content = str(payload.get("content", ""))
        append = bool(payload.get("append", True))

        if not path:
            return json.dumps(
                {"success": False, "message": "'path' alanı zorunludur."}, ensure_ascii=False
            )

        ok, msg = await asyncio.to_thread(
            self.code.write_generated_test, path, content, append=append
        )
        return json.dumps({"success": ok, "message": msg, "path": path}, ensure_ascii=False)

    async def _tool_run_pytest(self, arg: str) -> str:
        payload = self._parse_json_payload(arg)
        command = str(payload.get("command", "pytest -q")).strip() or "pytest -q"
        cwd = str(payload.get("cwd", self.cfg.BASE_DIR)).strip() or str(self.cfg.BASE_DIR)
        result = await asyncio.to_thread(self.code.run_pytest_and_collect, command, cwd)
        return json.dumps(result, ensure_ascii=False)

    async def _build_coverage_plan(self, payload: str) -> str:
        structured = self._parse_json_payload(payload)
        diagnosis = str(
            structured.pop(
                "diagnosis",
                "Coverage açığını kapatmak için hedefli pytest senaryoları ve CI remediation adımları öner.",
            )
        ).strip()
        remediation = build_ci_remediation_payload(structured, diagnosis)
        coverage = self._coverage_config_summary()
        suspected_targets = remediation.get("suspected_targets") or []
        suggested_tests = [self._suggest_test_path(path) for path in suspected_targets[:6]]
        return json.dumps(
            {
                "coverage": coverage,
                "remediation_loop": remediation.get("remediation_loop", {}),
                "suggested_tests": suggested_tests,
                "root_cause_summary": remediation.get("root_cause_summary", ""),
            },
            ensure_ascii=False,
        )

    async def run_task(self, task_prompt: str) -> str:
        prompt = (task_prompt or "").strip()
        if not prompt:
            return "[UYARI] Boş QA/Coverage görevi verildi."

        lower = prompt.lower()
        if lower == "coverage_config":
            return await self.call_tool("coverage_config", "")
        if lower.startswith("read_file|"):
            return await self.call_tool("read_file", prompt.split("|", 1)[1].strip())
        if lower.startswith("list_directory|"):
            return await self.call_tool("list_directory", prompt.split("|", 1)[1].strip())
        if lower.startswith("grep_search|"):
            return await self.call_tool("grep_search", prompt.split("|", 1)[1].strip())
        if lower.startswith("ci_remediation|"):
            return await self.call_tool("ci_remediation", prompt.split("|", 1)[1].strip())
        if lower.startswith("coverage_plan|"):
            return await self._build_coverage_plan(prompt.split("|", 1)[1].strip())
        if lower.startswith("write_file|"):
            return await self.call_tool("write_file", prompt.split("|", 1)[1].strip())
        if lower.startswith("run_pytest|"):
            return await self.call_tool("run_pytest", prompt.split("|", 1)[1].strip())
        if lower.startswith("write_missing_tests|"):
            parts = prompt.split("|", 2)
            target_path = parts[1].strip() if len(parts) > 1 else ""
            context = parts[2].strip() if len(parts) > 2 else ""
            generated = await self._generate_test_code(target_path.strip(), context.strip())
            test_path = self._suggest_test_path(target_path)
            ok, msg = await asyncio.to_thread(
                self.code.write_generated_test, test_path, generated, append=True
            )
            return json.dumps(
                {
                    "success": ok,
                    "target_path": target_path,
                    "test_path": test_path,
                    "message": msg,
                    "generated_test": generated,
                },
                ensure_ascii=False,
            )

        if any(
            keyword in lower
            for keyword in (
                "coverage",
                "kapsama",
                "eksik test",
                "pytest",
                "test yaz",
                "test üret",
                "qa",
            )
        ):
            return await self._build_coverage_plan(prompt)

        return await self._generate_test_code("", prompt)
