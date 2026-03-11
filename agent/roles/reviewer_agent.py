"""GitHub/PR/issue kalite kontrol odaklı uzman ajan."""

from __future__ import annotations

import asyncio
from typing import Optional

from config import Config
from managers.github_manager import GitHubManager

from agent.base_agent import BaseAgent


class ReviewerAgent(BaseAgent):
    """PR, issue ve repo gözden geçirme akışlarını yöneten uzman ajan."""

    SYSTEM_PROMPT = (
        "Sen bir reviewer ajansın. Kod yazmazsın; mevcut değişiklikleri, PR ve issue durumlarını "
        "analiz eder, risk odaklı ve kısa bir kalite raporu üretirsin."
    )

    def __init__(self, cfg: Optional[Config] = None) -> None:
        super().__init__(cfg=cfg, role_name="reviewer")
        self.github = GitHubManager(self.cfg.GITHUB_TOKEN, self.cfg.GITHUB_REPO)

        self.register_tool("repo_info", self._tool_repo_info)
        self.register_tool("list_prs", self._tool_list_prs)
        self.register_tool("pr_diff", self._tool_pr_diff)
        self.register_tool("list_issues", self._tool_list_issues)
        self.register_tool("run_tests", self._tool_run_tests)

    async def _tool_repo_info(self, _arg: str) -> str:
        ok, out = await asyncio.to_thread(self.github.get_repo_info)
        return out if ok else f"[HATA] {out}"

    async def _tool_list_prs(self, arg: str) -> str:
        state = (arg.strip() or "open").lower()
        ok, out = await asyncio.to_thread(self.github.list_pull_requests, state, 20)
        return out if ok else f"[HATA] {out}"

    async def _tool_pr_diff(self, arg: str) -> str:
        number = int(arg.strip()) if arg.strip().isdigit() else 0
        if number <= 0:
            return "⚠ Kullanım: pr_diff|<pr_no>"
        ok, out = await asyncio.to_thread(self.github.get_pull_request_diff, number)
        return out if ok else f"[HATA] {out}"

    async def _tool_list_issues(self, arg: str) -> str:
        state = (arg.strip() or "open").lower()
        ok, out = await asyncio.to_thread(self.github.list_issues, state, 20)
        return str(out) if ok else f"[HATA] {out}"

    async def _tool_run_tests(self, arg: str) -> str:
        command = (arg or "").strip() or "bash run_tests.sh"
        if not (command.startswith("bash run_tests.sh") or command.startswith("pytest")):
            return "⚠ Kullanım: run_tests|bash run_tests.sh veya run_tests|pytest ..."

        proc = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()

        out = (stdout or b"").decode("utf-8", errors="replace").strip()
        err = (stderr or b"").decode("utf-8", errors="replace").strip()
        status = "OK" if proc.returncode == 0 else f"FAIL({proc.returncode})"
        return (
            f"[TEST:{status}] komut={command}\n"
            f"[STDOUT]\n{out or '-'}\n"
            f"[STDERR]\n{err or '-'}"
        )

    async def run_task(self, task_prompt: str) -> str:
        prompt = (task_prompt or "").strip()
        if not prompt:
            return "[UYARI] Boş reviewer görevi verildi."

        lower = prompt.lower()
        if lower.startswith("repo_info"):
            return await self.call_tool("repo_info", "")
        if lower.startswith("list_prs"):
            arg = prompt.split("|", 1)[1].strip() if "|" in prompt else "open"
            return await self.call_tool("list_prs", arg)
        if lower.startswith("pr_diff|"):
            return await self.call_tool("pr_diff", prompt.split("|", 1)[1].strip())
        if lower.startswith("list_issues"):
            arg = prompt.split("|", 1)[1].strip() if "|" in prompt else "open"
            return await self.call_tool("list_issues", arg)
        if lower.startswith("run_tests"):
            arg = prompt.split("|", 1)[1].strip() if "|" in prompt else self.cfg.REVIEWER_TEST_COMMAND
            return await self.call_tool("run_tests", arg)
        if lower.startswith("review_code|"):
            context = prompt.split("|", 1)[1].strip()
            test_output = await self.call_tool("run_tests", self.cfg.REVIEWER_TEST_COMMAND)
            status = "PASS"
            risk = "düşük"
            if "[test:fail" in test_output.lower() or "fail(" in test_output.lower():
                status = "FAIL"
                risk = "yüksek"
            return (
                f"[REVIEW:{status}]\n"
                f"Risk: {risk}\n"
                f"Kod Özeti: {context[:500] or '-'}\n\n"
                f"Test Çıktısı:\n{test_output[:2000]}"
            )

        # Doğal dilde review niyeti varsa kalite turu + test çalıştır.
        if any(k in lower for k in ("review", "incele", "regresyon", "test")):
            return await self.run_task("review_code|Doğal dil inceleme isteği")

        return await self.call_tool("list_prs", "open")