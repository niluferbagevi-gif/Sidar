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
from core.rag import DocumentStore
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
        self._graph_docs: Optional[DocumentStore] = None

        self.register_tool("repo_info", self._tool_repo_info)
        self.register_tool("list_prs", self._tool_list_prs)
        self.register_tool("pr_diff", self._tool_pr_diff)
        self.register_tool("list_issues", self._tool_list_issues)
        self.register_tool("run_tests", self._tool_run_tests)
        self.register_tool("lsp_diagnostics", self._tool_lsp_diagnostics)
        self.register_tool("graph_impact", self._tool_graph_impact)

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
    def _build_graph_candidate_paths(code_context: str) -> list[str]:
        """GraphRAG etki analizi için anlamlı dosya adaylarını çıkarır."""
        supported_suffixes = (".py", ".ts", ".tsx", ".js", ".jsx")
        return [
            path for path in ReviewerAgent._extract_changed_paths(code_context)
            if path.endswith(supported_suffixes)
        ][:12]

    @staticmethod
    def _merge_candidate_paths(*path_groups: list[str]) -> list[str]:
        """Birden çok aday listesini sırayı koruyarak birleştirir."""
        merged: list[str] = []
        for group in path_groups:
            for path in group or []:
                normalized = (path or "").strip().lstrip("./")
                if not normalized or normalized in merged:
                    continue
                merged.append(normalized)
        return merged

    @staticmethod
    def _collect_graph_followup_paths(graph_payload: dict[str, object]) -> list[str]:
        """GraphRAG raporundan reviewer'ın genişletmesi gereken kod hedeflerini toplar."""
        reports = graph_payload.get("reports", []) if isinstance(graph_payload, dict) else []
        if not isinstance(reports, list):
            return []

        supported_suffixes = (".py", ".ts", ".tsx", ".js", ".jsx")
        collected: list[str] = []
        for item in reports:
            if not isinstance(item, dict) or not item.get("ok"):
                continue
            details = item.get("details") or {}
            if not isinstance(details, dict):
                continue
            for field in ("review_targets", "impacted_endpoint_handlers", "caller_files", "direct_dependents"):
                values = details.get(field) or []
                if not isinstance(values, list):
                    continue
                for path in values:
                    normalized = str(path or "").strip().lstrip("./")
                    if not normalized.endswith(supported_suffixes) or normalized in collected:
                        continue
                    collected.append(normalized)
        return collected

    @staticmethod
    def _summarize_graph_payload(graph_payload: dict[str, object]) -> dict[str, object]:
        """GraphRAG yapılandırılmış çıktısını reviewer kalite kapısı özeti hâline getirir."""
        reports = graph_payload.get("reports", []) if isinstance(graph_payload, dict) else []
        ok_reports = [item for item in reports if isinstance(item, dict) and item.get("ok")]
        if not ok_reports:
            return {
                "status": str((graph_payload or {}).get("status", "no-signal")),
                "risk": "düşük",
                "high_risk_targets": [],
                "followup_paths": [],
                "summary": str((graph_payload or {}).get("summary", "GraphRAG etki analizi üretilemedi.")),
            }

        followup_paths = ReviewerAgent._collect_graph_followup_paths(graph_payload)
        high_risk_targets: list[str] = []
        impacted_endpoints = 0
        for item in ok_reports:
            details = item.get("details") or {}
            if not isinstance(details, dict):
                continue
            if str(details.get("risk_level", "")).lower() == "high":
                high_risk_targets.append(str(item.get("target", "")))
            impacted_endpoints += len(details.get("impacted_endpoints") or [])

        risk = "orta" if high_risk_targets else "düşük"
        summary = (
            f"GraphRAG {len(ok_reports)} hedefi analiz etti; "
            f"yüksek riskli hedef={len(high_risk_targets)}, "
            f"genişletilmiş inceleme yolu={len(followup_paths)}, "
            f"etkilenen endpoint={impacted_endpoints}."
        )
        return {
            "status": str(graph_payload.get("status", "ok")),
            "risk": risk,
            "high_risk_targets": high_risk_targets,
            "followup_paths": followup_paths,
            "summary": summary,
        }

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

    def _get_graph_store(self) -> DocumentStore:
        if self._graph_docs is None:
            self._graph_docs = DocumentStore(
                Path(self.config.RAG_DIR),
                top_k=self.config.RAG_TOP_K,
                chunk_size=self.config.RAG_CHUNK_SIZE,
                chunk_overlap=self.config.RAG_CHUNK_OVERLAP,
                use_gpu=self.config.USE_GPU,
                gpu_device=self.config.GPU_DEVICE,
                mixed_precision=self.config.GPU_MIXED_PRECISION,
                cfg=self.config,
            )
        return self._graph_docs

    async def _tool_graph_impact(self, arg: str) -> str:
        candidates = self._build_graph_candidate_paths(arg)
        if not candidates:
            raw_target = (arg or "").strip()
            candidates = [raw_target] if raw_target else []
        if not candidates:
            return json.dumps(
                {
                    "status": "no-targets",
                    "summary": "GraphRAG etki analizi için uygun hedef bulunamadı.",
                    "targets": [],
                    "reports": [],
                },
                ensure_ascii=False,
            )

        docs = self._get_graph_store()
        reports = []
        for target in candidates:
            ok, details = await asyncio.to_thread(docs.graph_impact_details, target, 8)
            report = ""
            if ok:
                _, report = await asyncio.to_thread(docs.analyze_graph_impact, target, 8)
            else:
                report = str(details)
                details = {}
            reports.append({"target": target, "ok": ok, "report": report, "details": details})

        status = "ok" if any(item["ok"] for item in reports) else "no-signal"
        summary = (
            f"GraphRAG etki analizi {sum(1 for item in reports if item['ok'])} hedef için üretildi."
            if status == "ok"
            else "GraphRAG etki analizi üretilemedi."
        )
        return json.dumps(
            {
                "status": status,
                "summary": summary,
                "targets": candidates,
                "reports": reports,
            },
            ensure_ascii=False,
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
            arg = prompt.split("|", 1)[1].strip() if "|" in prompt else self.config.REVIEWER_TEST_COMMAND
            return await self.call_tool("run_tests", arg)
        if lower.startswith("lsp_diagnostics"):
            arg = prompt.split("|", 1)[1].strip() if "|" in prompt else ""
            return await self.call_tool("lsp_diagnostics", arg)
        if lower.startswith("graph_impact"):
            arg = prompt.split("|", 1)[1].strip() if "|" in prompt else ""
            return await self.call_tool("graph_impact", arg)

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

            await self.events.publish("reviewer", "GraphRAG etki analizi hazırlanıyor...")
            graph_output = await self.call_tool("graph_impact", context)
            graph_payload = {"status": "tool-error", "summary": "GraphRAG çıktısı çözümlenemedi.", "reports": []}
            with contextlib.suppress(json.JSONDecodeError):
                graph_payload = json.loads(graph_output)
            graph_summary = self._summarize_graph_payload(graph_payload)

            lsp_scope_paths = self._merge_candidate_paths(
                self._build_lsp_candidate_paths(context),
                list(graph_summary.get("followup_paths", []) or []),
            )
            await self.events.publish(
                "reviewer",
                f"LSP tabanlı semantik denetim çalıştırılıyor... hedef={len(lsp_scope_paths) or 1}",
            )
            lsp_output = await self.call_tool("lsp_diagnostics", " ".join(lsp_scope_paths))
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
            elif graph_summary["risk"] == "orta":
                risk = "orta"

            await self.events.publish("reviewer", "QA kararı coder ajanına P2P ile iletiliyor...")
            feedback_payload = json.dumps(
                {
                    "decision": decision,
                    "risk": risk,
                    "summary": (
                        f"[REVIEW:{status}] Dinamik + regresyon + LSP semantik denetimleri değerlendirildi. "
                        f"{semantic_report['summary']} {graph_summary['summary']}"
                    ),
                    "dynamic_test_output": dynamic_test_output,
                    "regression_test_output": regression_output,
                    "lsp_diagnostics_output": lsp_output,
                    "semantic_risk_report": semantic_report,
                    "graph_impact_output": graph_output,
                    "graph_impact_report": graph_payload,
                    "graph_review_scope": graph_summary,
                    "lsp_scope_paths": lsp_scope_paths or ["workspace:auto"],
                },
                ensure_ascii=False,
            )
            return self.delegate_to("coder", f"qa_feedback|{feedback_payload}", reason="review_decision")

        if any(k in lower for k in ("review", "incele", "regresyon", "test")):
            return await self.run_task("review_code|Doğal dil inceleme isteği")

        return await self.call_tool("list_prs", "open")