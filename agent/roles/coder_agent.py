"""Kod üretim/düzenleme odaklı uzman ajan."""

from __future__ import annotations

import asyncio
import inspect
import json
import re
from collections.abc import Callable
from typing import Any

from agent.base_agent import BaseAgent
from agent.core.contracts import DelegationRequest
from agent.core.event_stream import get_agent_event_bus
from agent.registry import AgentCatalog
from config import Config
from managers.code_manager import CodeManager
from managers.package_info import PackageInfoManager
from managers.security import SecurityManager
from managers.todo_manager import TodoManager


@AgentCatalog.register(
    capabilities=["code_generation", "file_io", "shell_execution", "code_review"], is_builtin=True
)
class CoderAgent(BaseAgent):
    """Yalnızca kodlama ve proje denetim araçlarını kullanan uzman ajan."""

    SYSTEM_PROMPT = (
        "Sen bir kodlayıcı ajansın. Sadece kod/dosya araçlarıyla çalışırsın. "
        "patch_file kullanırken hedef blok/satır bağlamını dikkatle korursun. "
        "Kod çalıştırma adımlarında güvenlik seviyesine uygun davranır, "
        "tehlikeli komutlardan kaçınırsın."
    )

    def __init__(
        self,
        cfg: Config | None = None,
        *,
        config: Config | None = None,
    ) -> None:
        resolved_cfg = cfg or config
        super().__init__(cfg=resolved_cfg, role_name="coder")
        self.security = SecurityManager(
            cfg=self.cfg,
            access_level=getattr(self.cfg, "ACCESS_LEVEL", "full"),
        )
        self.events = get_agent_event_bus()
        self.code = CodeManager(self.security, base_dir=self.cfg.BASE_DIR)
        self.pkg = PackageInfoManager(self.cfg)
        self.todo = TodoManager(cfg=self.cfg)

        self.register_tool("read_file", self._tool_read_file)
        self.register_tool("write_file", self._tool_write_file)
        self.register_tool("patch_file", self._tool_patch_file)
        self.register_tool("execute_code", self._tool_execute_code)
        self.register_tool("list_directory", self._tool_list_directory)
        self.register_tool("glob_search", self._tool_glob_search)
        self.register_tool("grep_search", self._tool_grep_search)
        self.register_tool("audit_project", self._tool_audit_project)
        self.register_tool("get_package_info", self._tool_get_package_info)
        self.register_tool("scan_project_todos", self._tool_scan_project_todos)

    async def _tool_read_file(self, arg: str) -> str:
        _ok, out = await asyncio.to_thread(self.code.read_file, arg)
        return out

    async def _tool_write_file(self, arg: str) -> str:
        parts = arg.split("|", 1)
        if len(parts) < 2:
            return "⚠ Kullanım: write_file|<path>|<content>"
        path, content = parts[0].strip(), parts[1]
        _ok, out = await asyncio.to_thread(self.code.write_file, path, content)
        return out

    async def _tool_patch_file(self, arg: str) -> str:
        parts = arg.split("|", 2)
        if len(parts) < 3:
            return "⚠ Kullanım: patch_file|<path>|<target_block>|<replacement_block>"
        path, target_block, replacement_block = parts[0].strip(), parts[1], parts[2]
        _ok, out = await asyncio.to_thread(
            self.code.patch_file, path, target_block, replacement_block
        )
        return out

    async def _tool_execute_code(self, arg: str) -> str:
        _ok, out = await asyncio.to_thread(self.code.execute_code, arg)
        return out

    async def _tool_list_directory(self, arg: str) -> str:
        _ok, out = await asyncio.to_thread(self.code.list_directory, arg or ".")
        return out

    async def _tool_glob_search(self, arg: str) -> str:
        pattern, base = (arg.split("|||", 1) + ["."])[:2]
        _ok, out = await asyncio.to_thread(
            self.code.glob_search, pattern.strip(), base.strip() or "."
        )
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

    async def _tool_audit_project(self, arg: str) -> str:
        return await asyncio.to_thread(self.code.audit_project, arg or ".")

    async def _tool_get_package_info(self, arg: str) -> str:
        _ok, out = await self.pkg.pypi_info(arg.strip())
        return out

    async def _tool_scan_project_todos(self, arg: str) -> str:
        directory = arg.strip() or str(self.cfg.BASE_DIR)
        return await asyncio.to_thread(self.todo.scan_project_todos, directory, None)

    @staticmethod
    def _parse_qa_feedback(raw_feedback: str) -> dict[str, Any]:
        payload = (raw_feedback or "").strip()
        if not payload:
            return {}
        if payload.startswith("{"):
            try:
                parsed = json.loads(payload)
                if isinstance(parsed, dict):
                    return parsed
            except json.JSONDecodeError:
                return {"raw": payload}
        result: dict[str, str] = {"raw": payload}
        for chunk in payload.split(";"):
            if "=" not in chunk:
                continue
            key, value = chunk.split("=", 1)
            result[key.strip().lower()] = value.strip()
        return result

    async def run_task(self, task_prompt: str) -> str | DelegationRequest:
        await self.events.publish("coder", "Kod görevi alındı, planlanıyor...")
        prompt = (task_prompt or "").strip()
        if not prompt:
            return "[UYARI] Boş kodlayıcı görevi verildi."

        lower = prompt.lower()
        if lower.startswith("read_file|"):
            return await self.call_tool("read_file", prompt.split("|", 1)[1])
        if lower.startswith("write_file|"):
            return await self.call_tool("write_file", prompt.split("|", 1)[1])
        if lower.startswith("patch_file|"):
            return await self.call_tool("patch_file", prompt.split("|", 1)[1])
        if lower.startswith("execute_code|"):
            return await self.call_tool("execute_code", prompt.split("|", 1)[1])

        if lower.startswith("qa_feedback|"):
            feedback = prompt.split("|", 1)[1].strip()
            parsed_feedback = self._parse_qa_feedback(feedback)
            decision = str(parsed_feedback.get("decision", "approve")).strip().lower()
            summary = str(parsed_feedback.get("summary", feedback)).strip()
            dynamic_output = str(parsed_feedback.get("dynamic_test_output", "")).strip()
            regression_output = str(parsed_feedback.get("regression_test_output", "")).strip()
            remediation_loop = (
                parsed_feedback.get("remediation_loop")
                if isinstance(parsed_feedback, dict)
                else None
            )
            remediation_summary = ""
            if isinstance(remediation_loop, dict):
                remediation_summary = str(remediation_loop.get("summary", "")).strip()
            failing_excerpt = "\n\n".join(
                part for part in (dynamic_output, regression_output) if part
            )[:1500]

            if decision == "reject":
                remediation_block = (
                    f"\n[REMEDIATION_LOOP] {remediation_summary}" if remediation_summary else ""
                )
                return (
                    "[CODER:REWORK_REQUIRED] Reviewer geri bildirimi alındı. "
                    f"Özet: {summary}{remediation_block}\n"
                    f"[QA_FEEDBACK] {feedback}\n"
                    f"[FAILED_TESTS] {failing_excerpt or '-'}"
                )
            return f"[CODER:APPROVED] Reviewer onayı alındı: {summary}"

        if lower.startswith("request_review|"):
            payload = prompt.split("|", 1)[1].strip()
            return self.delegate_to(
                "reviewer", f"review_code|{payload}", reason="coder_request_review"
            )

        # Basit doğal dil eşleme: "X isimli bir dosyaya 'Y' yaz"
        m = re.search(
            r"([\w./-]+\.\w+)\s+isimli\s+bir\s+dosyaya\s+['\"](.+?)['\"]\s+yaz",
            prompt,
            re.IGNORECASE,
        )
        if m:
            path = m.group(1)
            content = m.group(2)
            return await self.call_tool("write_file", f"{path}|{content}")

        return f"[LEGACY_FALLBACK] coder_unhandled task={prompt}"
    @staticmethod
    async def _call_maybe_async(
        func: Callable[..., Any], *args: Any, **kwargs: Any
    ) -> Any:
        result = func(*args, **kwargs)
        if inspect.isawaitable(result):
            return await result
        return result
