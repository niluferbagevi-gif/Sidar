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
        self.register_tool("read_test_artifacts", self._tool_read_test_artifacts)

    async def _tool_read_file(self, arg: str) -> str:
        _ok, out = await asyncio.to_thread(self.code.read_file, arg)
        return out

    async def _tool_write_file(self, arg: str) -> str:
        parts = arg.split("|", 1)
        if len(parts) < 2:
            return "⚠ Kullanım: write_file|<path>|<content>"
        path, content = parts[0].strip(), parts[1]
        _ok, out = await self.code.write_file_hitl(path, content)
        return out

    async def _tool_patch_file(self, arg: str) -> str:
        parts = arg.split("|", 2)
        if len(parts) < 3:
            return "⚠ Kullanım: patch_file|<path>|<target_block>|<replacement_block>"
        path, target_block, replacement_block = parts[0].strip(), parts[1], parts[2]
        _ok, out = await self.code.patch_file_hitl(path, target_block, replacement_block)
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

    async def _tool_read_test_artifacts(self, arg: str) -> str:
        """Coverage/junit benzeri test artefaktlarını hızlıca okur."""
        raw = (arg or "").strip()
        if not raw:
            return "[TEST_ARTIFACTS] {}"

        artifacts: dict[str, str] = {}
        for chunk in raw.split(";"):
            item = chunk.strip()
            if not item or "=" not in item:
                continue
            key, path = item.split("=", 1)
            resolved_key = key.strip() or "artifact"
            resolved_path = path.strip()
            if not resolved_path:
                continue
            _ok, out = await asyncio.to_thread(self.code.read_file, resolved_path)
            artifacts[resolved_key] = out
        return f"[TEST_ARTIFACTS] {json.dumps(artifacts, ensure_ascii=False)}"

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

    def _format_tool_contract(self) -> str:
        tool_names = ", ".join(sorted(getattr(self, "tools", {})))
        return (
            "Kullanabileceğin araçlar: "
            f"{tool_names}. "
            "Yanıtını JSON olarak ver. Araç gerekiyorsa "
            '{"tool_calls":[{"name":"read_file","arg":"path"}],"final":""}; '
            'iş bittiyse {"final":"özet ve yapılanlar"}. '
            "Sadece kayıtlı araç adlarını kullan; dosya değişikliklerinde önce dosyayı oku, sonra "
            "patch_file/write_file kullan."
        )

    @staticmethod
    def _parse_llm_tool_plan(raw: str) -> dict[str, Any]:
        text = (raw or "").strip()
        if not text:
            return {"final": ""}
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE).strip()
            text = re.sub(r"\s*```$", "", text).strip()
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            return {"final": raw}
        if isinstance(parsed, dict):
            return parsed
        if isinstance(parsed, list):
            return {"tool_calls": parsed, "final": ""}
        return {"final": str(parsed)}

    async def _run_llm_tool_loop(self, prompt: str) -> str:
        messages: list[dict[str, str]] = [
            {
                "role": "user",
                "content": (f"{self._format_tool_contract()}\n\nGörev: {prompt}"),
            }
        ]
        last_final = ""
        for _step in range(3):
            raw = await self.call_llm(
                messages, system_prompt=self.SYSTEM_PROMPT, temperature=0.2, json_mode=True
            )
            plan = self._parse_llm_tool_plan(raw)
            final = str(plan.get("final", "") or "").strip()
            if final:
                last_final = final

            tool_calls = plan.get("tool_calls") or plan.get("tools") or []
            if isinstance(tool_calls, dict):
                tool_calls = [tool_calls]
            if not isinstance(tool_calls, list) or not tool_calls:
                return last_final or str(raw).strip() or "[CODER:EMPTY_LLM_RESPONSE]"

            tool_results: list[dict[str, str]] = []
            for item in tool_calls[:5]:
                if not isinstance(item, dict):
                    continue
                name = str(item.get("name") or item.get("tool") or "").strip()
                arg = str(item.get("arg") or item.get("args") or item.get("input") or "")
                if name not in getattr(self, "tools", {}):
                    tool_results.append({"tool": name, "result": f"[HATA] Bilinmeyen araç: {name}"})
                    continue
                result = await self.call_tool(name, arg)
                tool_results.append({"tool": name, "result": result})

            if not tool_results:
                return last_final or str(raw).strip() or "[CODER:NO_VALID_TOOL_CALLS]"

            messages.append({"role": "assistant", "content": raw})
            messages.append(
                {
                    "role": "user",
                    "content": (
                        "Araç sonuçları:\n"
                        f"{json.dumps(tool_results, ensure_ascii=False)}\n"
                        "Bu sonuçlara göre devam et veya final JSON döndür."
                    ),
                }
            )

        return last_final or "[CODER:TOOL_LOOP_LIMIT] Araç döngüsü sınırına ulaşıldı."

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
        if lower.startswith("read_test_artifacts|"):
            return await self.call_tool("read_test_artifacts", prompt.split("|", 1)[1])

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

        return await self._run_llm_tool_loop(prompt)

    @staticmethod
    async def _call_maybe_async(func: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        result = func(*args, **kwargs)
        if inspect.isawaitable(result):
            return await result
        return result
