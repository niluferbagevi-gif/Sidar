"""GitHub/PR/issue kalite kontrol odaklı uzman ajan."""

from __future__ import annotations

import asyncio
import json
import re
import shlex
import uuid
from pathlib import Path
from typing import Optional

from config import Config
from managers.code_manager import CodeManager
from managers.github_manager import GitHubManager
from managers.security import SecurityManager

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

    TEST_GENERATION_PROMPT = (
        "Sen kıdemli bir Python QA mühendisisin. Verilen değişiklik özetini analiz et ve yalnızca ham pytest "
        "test kodu üret. Yanıtında açıklama, markdown çiti veya ek anlatım olmasın. "
        "Testler deterministik olmalı, ağ erişimi kullanmamalı ve yalnızca proje içi modüllere odaklanmalıdır. "
        "Dinamik import gerekiyorsa standart kütüphane ile güvenli yaklaşım kullan."
    )

    def __init__(self, cfg: Optional[Config] = None) -> None:
        super().__init__(cfg=cfg, role_name="reviewer")
        self.github = GitHubManager(self.cfg.GITHUB_TOKEN, self.cfg.GITHUB_REPO)
        self.events = get_agent_event_bus()
        self.security = SecurityManager(cfg=self.cfg)
        self.code = CodeManager(
            self.security,
            self.cfg.BASE_DIR,
            docker_image=getattr(self.cfg, "DOCKER_PYTHON_IMAGE", "python:3.11-alpine"),
            docker_exec_timeout=getattr(self.cfg, "DOCKER_EXEC_TIMEOUT", 10),
            cfg=self.cfg,
        )

        self.register_tool("repo_info", self._tool_repo_info)
        self.register_tool("list_prs", self._tool_list_prs)
        self.register_tool("pr_diff", self._tool_pr_diff)
        self.register_tool("list_issues", self._tool_list_issues)
        self.register_tool("run_tests", self._tool_run_tests)

    @staticmethod
    def _extract_python_code_block(raw_text: str) -> str:
        text = (raw_text or "").strip()
        fenced = re.search(r"```(?:python)?\s*(.*?)```", text, flags=re.DOTALL | re.IGNORECASE)
        if fenced:
            text = fenced.group(1).strip()
        return text

    @staticmethod
    def _fail_closed_test_content(reason: str) -> str:
        safe_reason = (reason or "bilinmeyen hata").replace("'''", "\\'\\'\\'")
        return (
            "def test_reviewer_dynamic_generation_fail_closed():\n"
            f"    raise AssertionError('''{safe_reason}''')\n"
        )

    async def _build_dynamic_test_content(self, code_context: str) -> str:
        """Kod bağlamına göre LLM destekli dinamik pytest içeriği üretir."""
        context = (code_context or "").strip()
        if not context:
            return self._fail_closed_test_content("Reviewer dinamik test üretimi için boş bağlam aldı.")

        prompt = (
            "Aşağıdaki kod/değişiklik bağlamı için anlamlı pytest senaryoları üret.\n"
            "- En az 1 test fonksiyonu olsun.\n"
            "- Gerekiyorsa importları sen ekle.\n"
            "- Ağ erişimi, rastgelelik veya dış servis kullanma.\n"
            "- Yanıt sadece çalıştırılabilir Python kodu olsun.\n\n"
            f"[KOD_BAGLAMI]\n{context[:6000]}"
        )

        try:
            llm_output = await self.call_llm(
                [{"role": "user", "content": prompt}],
                system_prompt=self.TEST_GENERATION_PROMPT,
                temperature=0.1,
                json_mode=False,
            )
        except Exception as exc:
            return self._fail_closed_test_content(
                f"Reviewer LLM dinamik test üretimi başarısız oldu: {exc}"
            )

        test_code = self._extract_python_code_block(llm_output)
        if "def test_" not in test_code:
            return self._fail_closed_test_content(
                "Reviewer LLM çıktısı geçerli pytest test fonksiyonu içermedi."
            )
        return test_code + ("\n" if not test_code.endswith("\n") else "")

    async def _run_dynamic_tests(self, code_context: str) -> str:
        test_content = await self._build_dynamic_test_content(code_context)
        temp_dir = Path(self.cfg.BASE_DIR) / "temp"
        temp_dir.mkdir(parents=True, exist_ok=True)
        dynamic_path = temp_dir / f"reviewer_dynamic_{uuid.uuid4().hex}.py"
        ok, write_msg = await asyncio.to_thread(self.code.write_file, str(dynamic_path), test_content, False)
        if not ok:
            return (
                "[TEST:FAIL-CLOSED] komut=dynamic_pytest\n"
                f"[STDOUT]\n-\n[STDERR]\n{write_msg}"
            )

        relative_path = dynamic_path.relative_to(self.cfg.BASE_DIR).as_posix()
        try:
            return await self.call_tool("run_tests", f"pytest -q {relative_path}")
        finally:
            try:
                dynamic_path.unlink(missing_ok=True)
            except Exception:
                pass

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

    def _build_sandbox_test_command(self, command: str) -> str:
        limits = self.code._resolve_sandbox_limits()
        workspace = shlex.quote(str(self.cfg.BASE_DIR))
        inner_command = shlex.quote(command)
        docker_image = shlex.quote(self.code.docker_image)
        runtime = self.code._resolve_runtime()
        runtime_part = f" --runtime {shlex.quote(runtime)}" if runtime else ""
        return (
            "docker run --rm"
            f" --memory={shlex.quote(str(limits['memory']))}"
            f" --cpus={shlex.quote(str(limits['cpus']))}"
            f" --pids-limit={int(limits['pids_limit'])}"
            f" --network={shlex.quote(str(limits['network_mode']))}"
            f" -v {workspace}:/workspace"
            " -w /workspace"
            f"{runtime_part} {docker_image} sh -lc {inner_command}"
        )

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
        command = (arg or "").strip() or self.cfg.REVIEWER_TEST_COMMAND
        allowed_prefixes = ("bash run_tests.sh", "pytest", "python -m pytest")
        if not command.startswith(allowed_prefixes):
            return "⚠ Kullanım: run_tests|bash run_tests.sh veya run_tests|pytest ..."
        if not self.code.docker_available:
            return (
                f"[TEST:FAIL-CLOSED] komut={command}\n"
                "[STDOUT]\n-\n"
                "[STDERR]\nDocker sandbox erişilemedi; Reviewer host shell fallback kullanmadan durduruldu."
            )

        sandbox_command = self._build_sandbox_test_command(command)
        ok, out = await asyncio.to_thread(
            self.code.run_shell,
            sandbox_command,
            str(self.cfg.BASE_DIR),
            False,
        )
        status = "OK" if ok else "FAIL-CLOSED"
        return (
            f"[TEST:{status}] komut={command}\n"
            f"[SANDBOX]\n{sandbox_command}\n"
            f"[OUTPUT]\n{out or '-'}"
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
            await self.events.publish("reviewer", "LLM tabanlı dinamik QA testleri üretiliyor...")
            dynamic_test_output = await self._run_dynamic_tests(context)

            await self.events.publish("reviewer", "Regresyon test planı hazırlanıyor...")
            regression_chunks = []
            for command in self._build_regression_commands(context):
                await self.events.publish("reviewer", f"Sandbox içinde test çalıştırılıyor: {command}")
                regression_chunks.append(await self.call_tool("run_tests", command))
            regression_output = "\n\n".join(regression_chunks)

            combo = f"{dynamic_test_output}\n\n{regression_output}".lower()
            status = "PASS"
            risk = "düşük"
            decision = "APPROVE"
            if "[test:fail" in combo or "[test:fail-closed" in combo or "komut başarısız" in combo:
                status = "FAIL"
                risk = "yüksek"
                decision = "REJECT"

            await self.events.publish("reviewer", "QA kararı coder ajanına P2P ile iletiliyor...")
            feedback_payload = json.dumps(
                {
                    "decision": decision,
                    "risk": risk,
                    "summary": f"[REVIEW:{status}] Dinamik + regresyon testleri değerlendirildi.",
                    "dynamic_test_output": dynamic_test_output,
                    "regression_test_output": regression_output,
                },
                ensure_ascii=False,
            )
            return self.delegate_to("coder", f"qa_feedback|{feedback_payload}", reason="review_decision")

        if any(k in lower for k in ("review", "incele", "regresyon", "test")):
            return await self.run_task("review_code|Doğal dil inceleme isteği")

        return await self.call_tool("list_prs", "open")
