"""GitHub/PR/issue kalite kontrol odaklı uzman ajan."""

from __future__ import annotations

import asyncio
import contextlib
import json
import re
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
        self.config = self.cfg
        self.github = GitHubManager(self.config.GITHUB_TOKEN, self.config.GITHUB_REPO)
        self.events = get_agent_event_bus()
        self.security = SecurityManager(cfg=self.config)
        self.code = CodeManager(
            self.security,
            self.config.BASE_DIR,
            docker_image=getattr(self.config, "DOCKER_PYTHON_IMAGE", "python:3.11-alpine"),
            docker_exec_timeout=getattr(self.config, "DOCKER_EXEC_TIMEOUT", 10),
            cfg=self.config,
        )

        self.register_tool("repo_info", self._tool_repo_info)
        self.register_tool("list_prs", self._tool_list_prs)
        self.register_tool("pr_diff", self._tool_pr_diff)
        self.register_tool("list_issues", self._tool_list_issues)
        self.register_tool("run_tests", self._tool_run_tests)
        self.register_tool("lsp_diagnostics", self._tool_lsp_diagnostics)

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
        temp_dir = Path(self.config.BASE_DIR) / "temp"
        temp_dir.mkdir(parents=True, exist_ok=True)
        dynamic_path = temp_dir / f"reviewer_dynamic_{uuid.uuid4().hex}.py"
        ok, write_msg = await asyncio.to_thread(self.code.write_file, str(dynamic_path), test_content, False)
        if not ok:
            return (
                "[TEST:FAIL-CLOSED] komut=dynamic_pytest\n"
                f"[STDOUT]\n-\n[STDERR]\n{write_msg}"
            )

        relative_path = dynamic_path.relative_to(self.config.BASE_DIR).as_posix()
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
        commands.append(self.config.REVIEWER_TEST_COMMAND)
        return list(dict.fromkeys(c.strip() for c in commands if (c or "").strip()))

    @staticmethod
    def _build_lsp_candidate_paths(code_context: str) -> list[str]:
        """LSP semantik denetimi için uygun dosya adaylarını çıkarır."""
        supported_suffixes = (".py", ".ts", ".tsx", ".js", ".jsx")
        return [
            path for path in ReviewerAgent._extract_changed_paths(code_context)
            if path.endswith(supported_suffixes)
        ][:32]

    @staticmethod
    def _summarize_lsp_diagnostics(output: str) -> dict[str, object]:
        """LSP diagnostics çıktısını semantik risk özetine dönüştürür."""
        text = (output or "").strip()
        if not text:
            return {
                "status": "clean",
                "risk": "düşük",
                "decision": "APPROVE",
                "counts": {},
                "summary": "LSP diagnostics çıktısı boş; semantik bulgu tespit edilmedi.",
            }

        with contextlib.suppress(json.JSONDecodeError):
            payload = json.loads(text)
            if isinstance(payload, dict) and payload.get("summary"):
                return {
                    "status": str(payload.get("status", "clean")),
                    "risk": str(payload.get("risk", "düşük")),
                    "decision": str(payload.get("decision", "APPROVE")),
                    "counts": dict(payload.get("counts", {}) or {}),
                    "summary": str(payload.get("summary", "")),
                    "issues": list(payload.get("issues", []) or []),
                }

        normalized = text.lower()
        if "temiz" in normalized and "severity=" not in normalized:
            return {
                "status": "clean",
                "risk": "düşük",
                "decision": "APPROVE",
                "counts": {},
                "summary": "LSP diagnostics temiz.",
            }
        if "bildirimi dönmedi" in normalized:
            return {
                "status": "no-signal",
                "risk": "orta",
                "decision": "APPROVE",
                "counts": {},
                "summary": "LSP diagnostics sinyali alınamadı; semantik denetim tamamlanamadı.",
            }
        if "hatası:" in normalized:
            return {
                "status": "tool-error",
                "risk": "orta",
                "decision": "APPROVE",
                "counts": {},
                "summary": "LSP diagnostics çalıştırılırken araç hatası oluştu.",
            }

        severity_counts: dict[int, int] = {}
        for line in text.splitlines():
            match = re.search(r"severity=(\d+)", line)
            if match:
                level = int(match.group(1))
                severity_counts[level] = severity_counts.get(level, 0) + 1

        total = sum(severity_counts.values())
        errors = severity_counts.get(1, 0)
        warnings = severity_counts.get(2, 0)
        infos = severity_counts.get(3, 0) + severity_counts.get(4, 0)

        if errors or warnings:
            risk = "yüksek" if errors else "orta"
            decision = "REJECT" if errors else "APPROVE"
            status = "issues-found"
            summary = (
                f"LSP semantik denetimi {total} bulgu üretti "
                f"(error={errors}, warning={warnings}, info={infos})."
            )
        elif total:
            risk = "düşük"
            decision = "APPROVE"
            status = "info-only"
            summary = f"LSP diagnostics yalnızca bilgilendirici {total} bulgu üretti."
        else:
            risk = "düşük"
            decision = "APPROVE"
            status = "clean"
            summary = "LSP diagnostics temiz."

        return {
            "status": status,
            "risk": risk,
            "decision": decision,
            "counts": severity_counts,
            "summary": summary,
        }

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
        command = (arg or "").strip() or self.config.REVIEWER_TEST_COMMAND
        allowed_prefixes = ("bash run_tests.sh", "pytest", "python -m pytest")
        if not command.startswith(allowed_prefixes):
            return "⚠ Kullanım: run_tests|bash run_tests.sh veya run_tests|pytest ..."
        ok, out = await asyncio.to_thread(
            self.code.run_shell_in_sandbox,
            command,
            str(self.config.BASE_DIR),
        )
        status = "OK" if ok else "FAIL-CLOSED"
        return (
            f"[TEST:{status}] komut={command}\n"
            f"[SANDBOX]\nDocker CLI sandbox üzerinden çalıştırıldı.\n"
            f"[OUTPUT]\n{out or '-'}"
        )

    async def _tool_lsp_diagnostics(self, arg: str) -> str:
        paths = self._build_lsp_candidate_paths(arg)
        _ok, audit = await asyncio.to_thread(self.code.lsp_semantic_audit, paths or None)
        payload = dict(audit or {})
        payload.setdefault("targets", paths or ["workspace:auto"])
        return json.dumps(payload, ensure_ascii=False)

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
            arg = prompt.split("|", 1)[1].strip() if "|" in prompt else self.config.REVIEWER_TEST_COMMAND
            return await self.call_tool("run_tests", arg)
        if lower.startswith("lsp_diagnostics"):
            arg = prompt.split("|", 1)[1].strip() if "|" in prompt else ""
            return await self.call_tool("lsp_diagnostics", arg)

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

            await self.events.publish("reviewer", "LSP tabanlı semantik denetim çalıştırılıyor...")
            lsp_output = await self.call_tool("lsp_diagnostics", context)
            semantic_report = self._summarize_lsp_diagnostics(lsp_output)

            combo = f"{dynamic_test_output}\n\n{regression_output}\n\n{lsp_output}".lower()
            status = "PASS"
            risk = "düşük"
            decision = "APPROVE"
            if "[test:fail" in combo or "[test:fail-closed" in combo or "komut başarısız" in combo:
                status = "FAIL"
                risk = "yüksek"
                decision = "REJECT"
            elif semantic_report["decision"] == "REJECT":
                status = "FAIL"
                risk = str(semantic_report["risk"])
                decision = "REJECT"
            elif semantic_report["risk"] == "orta":
                risk = "orta"

            await self.events.publish("reviewer", "QA kararı coder ajanına P2P ile iletiliyor...")
            feedback_payload = json.dumps(
                {
                    "decision": decision,
                    "risk": risk,
                    "summary": (
                        f"[REVIEW:{status}] Dinamik + regresyon + LSP semantik denetimleri değerlendirildi. "
                        f"{semantic_report['summary']}"
                    ),
                    "dynamic_test_output": dynamic_test_output,
                    "regression_test_output": regression_output,
                    "lsp_diagnostics_output": lsp_output,
                    "semantic_risk_report": semantic_report,
                },
                ensure_ascii=False,
            )
            return self.delegate_to("coder", f"qa_feedback|{feedback_payload}", reason="review_decision")

        if any(k in lower for k in ("review", "incele", "regresyon", "test")):
            return await self.run_task("review_code|Doğal dil inceleme isteği")

        return await self.call_tool("list_prs", "open")
