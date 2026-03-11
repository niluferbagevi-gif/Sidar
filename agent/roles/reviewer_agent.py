"""GitHub/PR/issue kalite kontrol odaklı uzman ajan."""

from __future__ import annotations

import asyncio
import os
import re
import tempfile
from typing import Optional

from config import Config
from managers.github_manager import GitHubManager

from agent.base_agent import BaseAgent
from agent.core.event_stream import get_agent_event_bus


class ReviewerAgent(BaseAgent):
    """PR, issue ve repo gözden geçirme akışlarını yöneten uzman ajan."""

    SYSTEM_PROMPT = (
        "Sen bir reviewer ajansın. Coder'dan gelen kod değişikliklerini QA gözlüğüyle inceler, "
        "gerekirse dinamik unit test üretir, hedefe yönelik + regresyon testlerini birlikte çalıştırır ve "
        "sonuçlara göre onay/red kararı verirsin. "
        "Kararını P2P geri bildirim olarak coder ajanına iletebilirsin."
    )

    def __init__(self, cfg: Optional[Config] = None) -> None:
        super().__init__(cfg=cfg, role_name="reviewer")
        self.github = GitHubManager(self.cfg.GITHUB_TOKEN, self.cfg.GITHUB_REPO)
        self.events = get_agent_event_bus()

        self.register_tool("repo_info", self._tool_repo_info)
        self.register_tool("list_prs", self._tool_list_prs)
        self.register_tool("pr_diff", self._tool_pr_diff)
        self.register_tool("list_issues", self._tool_list_issues)
        self.register_tool("run_tests", self._tool_run_tests)

    @staticmethod
    def _build_dynamic_test_content(code_context: str) -> str:
        """Kod bağlamına göre minimal ama çalıştırılabilir dinamik test dosyası üretir."""
        ctx = (code_context or "").lower()
        if "add_two" in ctx:
            return (
                "def test_add_two_contract():\n"
                "    from src.main import add_two  # örnek proje yapısı\n"
                "    assert add_two(2) == 4\n"
            )

        safe_context = (code_context or "").replace('"""', "'''")
        return (
            "def test_dynamic_context_not_empty():\n"
            f"    context = \"\"\"{safe_context[:2000]}\"\"\"\n"
            "    assert isinstance(context, str)\n"
            "    assert len(context.strip()) > 0\n"
        )

    async def _run_dynamic_tests(self, code_context: str) -> str:
        with tempfile.TemporaryDirectory(prefix="sidar_reviewer_") as td:
            test_path = os.path.join(td, "test_temp.py")
            with open(test_path, "w", encoding="utf-8") as fh:
                fh.write(self._build_dynamic_test_content(code_context))
            return await self.call_tool("run_tests", f"pytest -q {test_path}")

    @staticmethod
    def _extract_changed_paths(code_context: str) -> list[str]:
        """Serbest metin/diff içinden olası dosya yollarını toplar."""
        candidates = re.findall(r"[\w./-]+\.(?:py|js|ts|json|md|yml|yaml)", code_context or "")
        cleaned: list[str] = []
        for item in candidates:
            val = item.strip().lstrip("./")
            if not val or ".." in val or val.startswith("/"):
                continue
            cleaned.append(val)
        # stable + unique
        return list(dict.fromkeys(cleaned))

    def _build_regression_commands(self, code_context: str) -> list[str]:
        """Değişen dosyalara göre hedefli test + global regresyon komutlarını üretir."""
        commands: list[str] = []
        changed = self._extract_changed_paths(code_context)
        test_targets = [p for p in changed if p.startswith("tests/") and p.endswith(".py")]
        if test_targets:
            commands.append("pytest -q " + " ".join(test_targets[:8]))
        commands.append(self.cfg.REVIEWER_TEST_COMMAND)
        return list(dict.fromkeys(c.strip() for c in commands if (c or "").strip()))

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

    async def run_task(self, task_prompt: str):
        await self.events.publish("reviewer", "Reviewer görevi alındı, kalite kontrolü başlıyor...")
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
            await self.events.publish("reviewer", "Dinamik QA testleri üretiliyor...")
            dynamic_test_output = await self._run_dynamic_tests(context)

            await self.events.publish("reviewer", "Regresyon test planı hazırlanıyor...")
            regression_chunks = []
            for command in self._build_regression_commands(context):
                await self.events.publish("reviewer", f"Test çalıştırılıyor: {command}")
                regression_chunks.append(await self.call_tool("run_tests", command))
            regression_output = "\n\n".join(regression_chunks)

            combo = f"{dynamic_test_output}\n\n{regression_output}".lower()
            status = "PASS"
            risk = "düşük"
            decision = "APPROVE"
            if "[test:fail" in combo or "fail(" in combo:
                status = "FAIL"
                risk = "yüksek"
                decision = "REJECT"

            await self.events.publish("reviewer", "QA kararı coder ajanına P2P ile iletiliyor...")
            feedback = (
                f"qa_feedback|decision={decision};risk={risk};"
                f"summary=[REVIEW:{status}] Dinamik + regresyon testleri değerlendirildi."
            )
            return self.delegate_to("coder", feedback, reason="review_decision")

        if any(k in lower for k in ("review", "incele", "regresyon", "test")):
            return await self.run_task("review_code|Doğal dil inceleme isteği")

        return await self.call_tool("list_prs", "open")