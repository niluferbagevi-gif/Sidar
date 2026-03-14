# 🚀 Sidar 3.0.0 - Otomatik Dağıtım

"""Kod üretim/düzenleme odaklı uzman ajan."""

from __future__ import annotations

import asyncio
import re
from typing import Optional

from config import Config
from managers.code_manager import CodeManager
from managers.package_info import PackageInfoManager
from managers.security import SecurityManager
from managers.todo_manager import TodoManager

from agent.base_agent import BaseAgent
from agent.core.event_stream import get_agent_event_bus


class CoderAgent(BaseAgent):
    """Yalnızca kodlama ve proje denetim araçlarını kullanan uzman ajan."""

    SYSTEM_PROMPT = (
        "Sen bir kodlayıcı ajansın. Sadece kod/dosya araçlarıyla çalışırsın. "
        "patch_file kullanırken hedef blok/satır bağlamını dikkatle korursun. "
        "Kod çalıştırma adımlarında güvenlik seviyesine uygun davranır, "
        "tehlikeli komutlardan kaçınırsın."
    )

    def __init__(self, cfg: Optional[Config] = None) -> None:
        super().__init__(cfg=cfg, role_name="coder")
        self.security = SecurityManager(cfg=self.cfg)
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
        _ok, out = await asyncio.to_thread(self.code.patch_file, path, target_block, replacement_block)
        return out

    async def _tool_execute_code(self, arg: str) -> str:
        _ok, out = await asyncio.to_thread(self.code.execute_code, arg)
        return out

    async def _tool_list_directory(self, arg: str) -> str:
        _ok, out = await asyncio.to_thread(self.code.list_directory, arg or ".")
        return out

    async def _tool_glob_search(self, arg: str) -> str:
        pattern, base = (arg.split("|||", 1) + ["."])[:2]
        _ok, out = await asyncio.to_thread(self.code.glob_search, pattern.strip(), base.strip() or ".")
        return out

    async def _tool_grep_search(self, arg: str) -> str:
        parts = arg.split("|||", 3)
        pattern = parts[0].strip() if parts else ""
        path = parts[1].strip() if len(parts) > 1 else "."
        file_glob = parts[2].strip() if len(parts) > 2 else "*"
        context_lines = int(parts[3].strip()) if len(parts) > 3 and parts[3].strip().isdigit() else 2
        _ok, out = await asyncio.to_thread(self.code.grep_files, pattern, path, file_glob, context_lines)
        return out

    async def _tool_audit_project(self, arg: str) -> str:
        return await asyncio.to_thread(self.code.audit_project, arg or ".")

    async def _tool_get_package_info(self, arg: str) -> str:
        _ok, out = await self.pkg.pypi_info(arg.strip())
        return out

    async def _tool_scan_project_todos(self, arg: str) -> str:
        directory = arg.strip() or str(self.cfg.BASE_DIR)
        return await asyncio.to_thread(self.todo.scan_project_todos, directory, None)

    async def run_task(self, task_prompt: str) -> str:
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
            if "decision=reject" in feedback.lower():
                return f"[CODER:REWORK_REQUIRED] Reviewer geri bildirimi alındı: {feedback}"
            return f"[CODER:APPROVED] Reviewer onayı alındı: {feedback}"

        if lower.startswith("request_review|"):
            payload = prompt.split("|", 1)[1].strip()
            return self.delegate_to("reviewer", f"review_code|{payload}", reason="coder_request_review")

        # Basit doğal dil eşleme: "X isimli bir dosyaya 'Y' yaz"
        m = re.search(r"([\w./-]+\.\w+)\s+isimli\s+bir\s+dosyaya\s+['\"](.+?)['\"]\s+yaz", prompt, re.IGNORECASE)
        if m:
            path = m.group(1)
            content = m.group(2)
            return await self.call_tool("write_file", f"{path}|{content}")

        return f"[LEGACY_FALLBACK] coder_unhandled task={prompt}"