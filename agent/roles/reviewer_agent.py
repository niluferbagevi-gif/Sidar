"""GitHub/PR/issue kalite kontrol odaklı uzman ajan."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import re
import uuid
from collections.abc import Mapping, Sequence
from pathlib import Path

from agent.base_agent import BaseAgent
from agent.core.event_stream import get_agent_event_bus
from agent.registry import AgentCatalog
from config import Config
from core.rag import DocumentStore
from managers.browser_manager import BrowserManager
from managers.code_manager import CodeManager
from managers.github_manager import GitHubManager
from managers.security import SecurityManager

logger = logging.getLogger(__name__)

@AgentCatalog.register(
    capabilities=["code_review", "security_audit", "quality_check"], is_builtin=True
)
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

    def __init__(
        self,
        cfg: Config | None = None,
        *,
        config: Config | None = None,
    ) -> None:
        resolved_cfg = cfg or config
        super().__init__(cfg=resolved_cfg, role_name="reviewer")
        self.config = self.cfg
        github_token = str(getattr(self.config, "GITHUB_TOKEN", "") or "")
        github_repo = getattr(self.config, "GITHUB_REPO", None)
        assert github_repo is not None, "github_repo cannot be None"
        self.github = GitHubManager(github_token, str(github_repo))
        self.events = get_agent_event_bus()
        self.security = SecurityManager(cfg=self.config)
        self.code = CodeManager(
            self.security,
            self.config.BASE_DIR,
            docker_image=getattr(self.config, "DOCKER_PYTHON_IMAGE", "python:3.11-alpine"),
            docker_exec_timeout=getattr(self.config, "DOCKER_EXEC_TIMEOUT", 10),
            cfg=self.config,
        )
        self.browser = BrowserManager(self.config)
        self._graph_docs: DocumentStore | None = None

        self.register_tool("repo_info", self._tool_repo_info)
        self.register_tool("list_prs", self._tool_list_prs)
        self.register_tool("pr_diff", self._tool_pr_diff)
        self.register_tool("list_issues", self._tool_list_issues)
        self.register_tool("run_tests", self._tool_run_tests)
        self.register_tool("lsp_diagnostics", self._tool_lsp_diagnostics)
        self.register_tool("graph_impact", self._tool_graph_impact)
        self.register_tool("browser_signals", self._tool_browser_signals)

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
            return self._fail_closed_test_content(
                "Reviewer dinamik test üretimi için boş bağlam aldı."
            )

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
        ok, write_msg = await asyncio.to_thread(
            self.code.write_file, str(dynamic_path), test_content, False
        )
        if not ok:
            return "[TEST:FAIL-CLOSED] komut=dynamic_pytest\n" f"[STDOUT]\n-\n[STDERR]\n{write_msg}"

        relative_path = dynamic_path.relative_to(self.config.BASE_DIR).as_posix()
        try:
            return str(await self.call_tool("run_tests", f"pytest -q {relative_path}"))
        finally:
            try:
                dynamic_path.unlink(missing_ok=True)
            except Exception as exc:
                logger.debug("Temporary dynamic test file cleanup skipped: %s", exc)

    @staticmethod
    def _extract_changed_paths(code_context: str) -> list[str]:
        """Serbest metin/diff içinden olası dosya yollarını toplar."""
        candidates = re.findall(
            r"[\w./-]+\.(?:py|tsx|ts|jsx|js|json|md|yml|yaml)", code_context or ""
        )
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
        commands.append(getattr(self.config, "REVIEWER_TEST_COMMAND", "python -m pytest"))
        return list(dict.fromkeys(c.strip() for c in commands if (c or "").strip()))

    @staticmethod
    def _build_lsp_candidate_paths(code_context: str) -> list[str]:
        """LSP semantik denetimi için uygun dosya adaylarını çıkarır."""
        supported_suffixes = (".py", ".ts", ".tsx", ".js", ".jsx")
        return [
            path
            for path in ReviewerAgent._extract_changed_paths(code_context)
            if path.endswith(supported_suffixes)
        ][:32]

    @staticmethod
    def _build_graph_candidate_paths(code_context: str) -> list[str]:
        """GraphRAG etki analizi için anlamlı dosya adaylarını çıkarır."""
        supported_suffixes = (".py", ".ts", ".tsx", ".js", ".jsx")
        return [
            path
            for path in ReviewerAgent._extract_changed_paths(code_context)
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
    def _collect_graph_followup_paths(graph_payload: Mapping[str, object]) -> list[str]:
        """GraphRAG raporundan reviewer'ın genişletmesi gereken kod hedeflerini toplar."""
        reports = graph_payload.get("reports", [])
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
            for field in (
                "review_targets",
                "impacted_endpoint_handlers",
                "caller_files",
                "direct_dependents",
            ):
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
    def _to_int(value: object, default: int = 0) -> int:
        if isinstance(value, bool):
            return int(value)
        if isinstance(value, int):
            return value
        if isinstance(value, float):
            return int(value)
        if isinstance(value, str):
            with contextlib.suppress(ValueError):
                return int(value)
        return default

    @staticmethod
    def _as_str_list(value: object) -> list[str]:
        if not isinstance(value, list):
            return []
        return [str(item).strip() for item in value if str(item).strip()]

    @staticmethod
    def _as_mapping(value: object) -> Mapping[str, object]:
        return value if isinstance(value, Mapping) else {}

    @staticmethod
    def _summarize_graph_payload(graph_payload: Mapping[str, object]) -> dict[str, object]:
        """GraphRAG yapılandırılmış çıktısını reviewer kalite kapısı özeti hâline getirir."""
        reports_obj = graph_payload.get("reports", [])
        reports = reports_obj if isinstance(reports_obj, list) else []
        ok_reports = [item for item in reports if isinstance(item, dict) and item.get("ok")]
        if not ok_reports:
            return {
                "status": str(graph_payload.get("status", "no-signal")),
                "risk": "düşük",
                "high_risk_targets": [],
                "followup_paths": [],
                "summary": str(
                    graph_payload.get("summary", "GraphRAG etki analizi üretilemedi.")
                ),
            }

        followup_paths = ReviewerAgent._collect_graph_followup_paths(dict(graph_payload))
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

    @staticmethod
    def _normalize_issue_path(path: object) -> str:
        """LSP issue yolunu repo-köküne göre normalize eder."""
        value = str(path or "").strip().replace("\\", "/")
        marker = "/workspace/Sidar/"
        if marker in value:
            value = value.split(marker, 1)[1]
        return value.lstrip("./")

    @staticmethod
    def _build_combined_impact_report(
        semantic_report: Mapping[str, object],
        graph_summary: Mapping[str, object],
        direct_scope_paths: list[str],
        lsp_scope_paths: list[str],
    ) -> dict[str, object]:
        """GraphRAG ve LSP sinyallerini birleşik etki analizi olarak toplar."""
        followup_paths = ReviewerAgent._as_str_list(graph_summary.get("followup_paths", []))
        graph_followups = [
            str(path or "").strip().lstrip("./")
            for path in followup_paths
            if str(path or "").strip()
        ]
        issues_obj = semantic_report.get("issues", [])
        issues: Sequence[object] = issues_obj if isinstance(issues_obj, Sequence) else []
        normalized_issue_paths: list[str] = []
        for item in issues:
            if not isinstance(item, dict):
                continue
            normalized = ReviewerAgent._normalize_issue_path(item.get("path"))
            if normalized and normalized not in normalized_issue_paths:
                normalized_issue_paths.append(normalized)

        direct_paths = [
            str(path or "").strip().lstrip("./")
            for path in direct_scope_paths
            if str(path or "").strip()
        ]
        indirect_paths = [
            path
            for path in graph_followups
            if path in normalized_issue_paths and path not in direct_paths
        ]
        highest_severity = 0
        counts_map = ReviewerAgent._as_mapping(semantic_report.get("counts", {}))
        for key, count in counts_map.items():
            try:
                severity = int(key)
            except (TypeError, ValueError):
                continue
            if ReviewerAgent._to_int(count, 0) > 0:
                highest_severity = min(severity, highest_severity) if highest_severity else severity

        if indirect_paths and highest_severity == 1:
            impact_level = "critical"
        elif indirect_paths or str(graph_summary.get("risk", "düşük")) == "orta":
            impact_level = "high"
        elif normalized_issue_paths:
            impact_level = "medium"
        else:
            impact_level = "low"

        return {
            "impact_level": impact_level,
            "direct_scope_paths": direct_paths,
            "graph_followup_paths": graph_followups,
            "issue_paths": normalized_issue_paths,
            "indirect_breakage_paths": indirect_paths,
            "high_risk_targets": ReviewerAgent._as_str_list(
                graph_summary.get("high_risk_targets", [])
            ),
            "summary": (
                f"Birleşik etki analizi: doğrudan hedef={len(direct_paths)}, "
                f"GraphRAG genişleme={len(graph_followups)}, "
                f"LSP issue dosyası={len(normalized_issue_paths)}, "
                f"dolaylı kırılma={len(indirect_paths)}."
            ),
        }

    @staticmethod
    def _build_fix_recommendations(
        semantic_report: Mapping[str, object],
        graph_payload: Mapping[str, object],
        combined_impact: Mapping[str, object],
    ) -> list[dict[str, object]]:
        """Reviewer için otomatik düzeltme önerisi adaylarını üretir."""
        recommendations: list[dict[str, object]] = []
        issues_obj = semantic_report.get("issues", [])
        issues: Sequence[object] = issues_obj if isinstance(issues_obj, Sequence) else []
        grouped_by_path: dict[str, list[dict[str, object]]] = {}
        for item in issues:
            if not isinstance(item, dict):
                continue
            normalized = ReviewerAgent._normalize_issue_path(item.get("path"))
            if not normalized:
                continue
            grouped_by_path.setdefault(normalized, []).append(item)

        graph_details_by_target: dict[str, dict[str, object]] = {}
        reports_obj = graph_payload.get("reports", [])
        reports: Sequence[object] = reports_obj if isinstance(reports_obj, Sequence) else []
        for report in reports:
            if not isinstance(report, dict) or not report.get("ok"):
                continue
            details = report.get("details") or {}
            if isinstance(details, dict):
                graph_details_by_target[str(report.get("target", "")).strip()] = details

        for path in ReviewerAgent._as_str_list(combined_impact.get("indirect_breakage_paths", [])):
            issue_group = grouped_by_path.get(path, [])
            messages = [
                str(item.get("message", "")).strip()
                for item in issue_group[:3]
                if str(item.get("message", "")).strip()
            ]
            related_graph_detail: Mapping[str, object] = next(
                (
                    details
                    for details in graph_details_by_target.values()
                    if path in ReviewerAgent._as_str_list(details.get("review_targets", []))
                    or path
                    in ReviewerAgent._as_str_list(details.get("impacted_endpoint_handlers", []))
                    or path in ReviewerAgent._as_str_list(details.get("caller_files", []))
                    or path in ReviewerAgent._as_str_list(details.get("direct_dependents", []))
                ),
                {},
            )
            recommendations.append(
                {
                    "path": path,
                    "reason": "graph+semantic",
                    "action": (
                        "GraphRAG tarafından genişletilen bu dosyada LSP bulguları var; "
                        "import/type sözleşmelerini ve etkilenen çağrı zincirini düzelt."
                    ),
                    "lsp_messages": messages,
                    "related_endpoints": ReviewerAgent._as_str_list(
                        related_graph_detail.get("impacted_endpoints", [])
                    ),
                }
            )

        if not recommendations:
            graph_followups: list[dict[str, object]] = []
            for report in reports:
                if not isinstance(report, dict) or not report.get("ok"):
                    continue
                target = str(report.get("target", "")).strip()
                details = report.get("details") or {}
                if not isinstance(details, dict):
                    continue
                if str(details.get("risk_level", "")).lower() != "high":
                    continue
                for field in (
                    "review_targets",
                    "impacted_endpoint_handlers",
                    "caller_files",
                    "direct_dependents",
                ):
                    values = details.get(field) or []
                    if not isinstance(values, list):
                        continue
                    for candidate in values:
                        normalized = str(candidate or "").strip().lstrip("./")
                        if not normalized or normalized == target:
                            continue
                        graph_followups.append(
                            {
                                "path": normalized,
                                "reason": "graph",
                                "action": (
                                    "GraphRAG yüksek riskli genişleme sinyali verdi; bu dosyada import/sözleşme "
                                    "uyumunu ve etkilenen çağrı zincirini doğrula."
                                ),
                                "lsp_messages": [],
                                "related_endpoints": ReviewerAgent._as_str_list(
                                    details.get("impacted_endpoints", [])
                                ),
                            }
                        )

            for item in graph_followups:
                if any(existing.get("path") == item.get("path") for existing in recommendations):
                    continue
                recommendations.append(item)

        if not recommendations:
            for path, issue_group in list(grouped_by_path.items())[:6]:
                messages = [
                    str(item.get("message", "")).strip()
                    for item in issue_group[:3]
                    if str(item.get("message", "")).strip()
                ]
                recommendations.append(
                    {
                        "path": path,
                        "reason": "semantic",
                        "action": "LSP hatalarını düzelt ve ilgili testleri yeniden çalıştır.",
                        "lsp_messages": messages,
                        "related_endpoints": [],
                    }
                )

        return recommendations[:8]

    @staticmethod
    def _parse_review_payload(raw_context: str) -> dict[str, object]:
        """review_code girdisinden kod bağlamı ve browser metadata çıkarır."""
        text = (raw_context or "").strip()
        if not text:
            return {
                "review_context": "",
                "browser_session_id": "",
                "browser_signals": {},
                "browser_include_dom": False,
                "browser_include_screenshot": False,
            }
        if text.startswith("{"):
            with contextlib.suppress(json.JSONDecodeError):
                payload = json.loads(text)
                if isinstance(payload, dict):
                    return {
                        "review_context": str(
                            payload.get("review_context")
                            or payload.get("code_context")
                            or payload.get("context")
                            or payload.get("changes")
                            or ""
                        ).strip(),
                        "browser_session_id": str(payload.get("browser_session_id") or "").strip(),
                        "browser_signals": dict(payload.get("browser_signals") or {}),
                        "browser_include_dom": bool(payload.get("browser_include_dom", False)),
                        "browser_include_screenshot": bool(
                            payload.get("browser_include_screenshot", False)
                        ),
                    }
        match = re.search(r"(?:browser_session_id|browser_session)=([A-Za-z0-9._:-]+)", text)
        cleaned = re.sub(
            r"(?:browser_session_id|browser_session)=([A-Za-z0-9._:-]+)", "", text
        ).strip()
        return {
            "review_context": cleaned or text,
            "browser_session_id": match.group(1) if match else "",
            "browser_signals": {},
            "browser_include_dom": False,
            "browser_include_screenshot": False,
        }

    @staticmethod
    def _summarize_browser_signals(
        browser_payload: Mapping[str, object] | None,
    ) -> dict[str, object]:
        payload = dict(browser_payload or {})
        summary = str(payload.get("summary", "") or "").strip()
        risk = str(payload.get("risk", "düşük") or "düşük")
        status = str(payload.get("status", "no-signal") or "no-signal")
        failed_actions = [
            str(item).strip()
            for item in ReviewerAgent._as_str_list(payload.get("failed_actions", []))
            if str(item).strip()
        ]
        pending_actions = [
            str(item).strip()
            for item in ReviewerAgent._as_str_list(payload.get("pending_actions", []))
            if str(item).strip()
        ]
        high_risk_actions = [
            str(item).strip()
            for item in ReviewerAgent._as_str_list(payload.get("high_risk_actions", []))
            if str(item).strip()
        ]
        return {
            "status": status,
            "risk": risk,
            "failed_actions": failed_actions[:8],
            "pending_actions": pending_actions[:8],
            "high_risk_actions": high_risk_actions[:8],
            "current_url": str(payload.get("current_url", "") or "").strip(),
            "summary": summary or "Browser sinyali alınamadı.",
        }

    @staticmethod
    def _build_browser_fix_recommendations(
        browser_summary: Mapping[str, object],
    ) -> list[dict[str, object]]:
        failed_actions = ReviewerAgent._as_str_list(browser_summary.get("failed_actions", []))
        pending_actions = ReviewerAgent._as_str_list(browser_summary.get("pending_actions", []))
        high_risk_actions = ReviewerAgent._as_str_list(
            browser_summary.get("high_risk_actions", [])
        )
        if not any((failed_actions, pending_actions, high_risk_actions)):
            return []
        return [
            {
                "path": str(browser_summary.get("current_url", "") or "browser:session"),
                "reason": "browser-signal",
                "action": (
                    "Dinamik browser akışındaki başarısız veya onay bekleyen adımları yeniden üret; "
                    "selector/DOM drift, izin akışı ve UI mutasyon yan etkilerini düzelt."
                ),
                "failed_actions": failed_actions[:4],
                "pending_actions": pending_actions[:4],
                "high_risk_actions": high_risk_actions[:4],
            }
        ]

    @staticmethod
    def _build_remediation_loop(
        semantic_report: Mapping[str, object],
        graph_summary: Mapping[str, object],
        combined_impact: Mapping[str, object],
        fix_recommendations: list[dict[str, object]],
        regression_commands: list[str],
    ) -> dict[str, object]:
        """Reviewer kalite kapısını kontrollü self-healing döngüsüne dönüştürür."""
        scoped_paths = ReviewerAgent._merge_candidate_paths(
            ReviewerAgent._as_str_list(combined_impact.get("direct_scope_paths", [])),
            ReviewerAgent._as_str_list(combined_impact.get("graph_followup_paths", [])),
            ReviewerAgent._as_str_list(combined_impact.get("issue_paths", [])),
            [
                str(item.get("path", "")).strip()
                for item in fix_recommendations
                if str(item.get("path", "")).strip()
            ],
        )
        issue_count = sum(
            ReviewerAgent._to_int(v, 0)
            for v in ReviewerAgent._as_mapping(semantic_report.get("counts", {})).values()
        )
        impact_level = str(combined_impact.get("impact_level", "low") or "low")
        graph_risk = str(graph_summary.get("risk", "düşük") or "düşük")
        needs_human_approval = impact_level in {"high", "critical"} or graph_risk == "orta"
        is_blocked = (
            bool(fix_recommendations) or issue_count > 0 or impact_level in {"high", "critical"}
        )
        mode = "self_heal_with_hitl" if needs_human_approval else "self_heal"
        status = "planned" if is_blocked else "observe_only"
        validation_commands = list(
            dict.fromkeys((regression_commands or []) + ["python -m pytest"])
        )[:4]
        return {
            "status": status,
            "mode": mode,
            "needs_human_approval": needs_human_approval,
            "max_auto_attempts": 1 if needs_human_approval else 2,
            "scope_paths": scoped_paths[:16],
            "validation_commands": validation_commands,
            "recommendation_count": len(fix_recommendations),
            "blocked_by": [
                reason
                for reason, active in (
                    ("semantic_issues", issue_count > 0),
                    (
                        "graph_indirect_breakage",
                        bool(combined_impact.get("indirect_breakage_paths")),
                    ),
                    ("high_graph_risk", graph_risk == "orta"),
                )
                if active
            ],
            "steps": [
                {
                    "name": "diagnose",
                    "status": "completed",
                    "detail": semantic_report.get("summary")
                    or graph_summary.get("summary")
                    or "Kalite kapısı tamamlandı.",
                },
                {
                    "name": "patch",
                    "status": "pending" if fix_recommendations else "skipped",
                    "detail": (
                        "Öncelikli remediation önerileri hazırlandı."
                        if fix_recommendations
                        else "Otomatik düzeltme gerektiren bulgu tespit edilmedi."
                    ),
                },
                {
                    "name": "validate",
                    "status": "pending" if is_blocked else "ready",
                    "detail": "Hedefli regresyon ve global pytest komutları sıraya alındı.",
                },
                {
                    "name": "handoff",
                    "status": "pending" if is_blocked else "ready",
                    "detail": (
                        "Riskli remediation için HITL onayı sonrası coder ajanına uygulanabilir plan devredilecek."
                        if needs_human_approval
                        else "Plan coder ajanına doğrudan uygulanabilir şekilde devredilecek."
                    ),
                },
            ],
            "summary": (
                f"Remediation loop hazır: mod={mode}, kapsam={len(scoped_paths[:16])} dosya, "
                f"öneri={len(fix_recommendations)}, doğrulama={len(validation_commands)} komut."
            ),
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

    async def _tool_browser_signals(self, arg: str) -> str:
        request = self._parse_review_payload(arg)
        session_id = str(request.get("browser_session_id", "") or "").strip()
        inline_payload = dict(ReviewerAgent._as_mapping(request.get("browser_signals", {})))
        if inline_payload:
            return json.dumps(inline_payload, ensure_ascii=False)
        if not session_id:
            return json.dumps(
                {
                    "status": "no-signal",
                    "risk": "düşük",
                    "summary": "Browser session_id verilmediği için sinyal toplanamadı.",
                },
                ensure_ascii=False,
            )
        signal = await asyncio.to_thread(
            self.browser.collect_session_signals,
            session_id,
            include_dom=bool(request.get("browser_include_dom", False)),
            include_screenshot=bool(request.get("browser_include_screenshot", False)),
        )
        return json.dumps(signal, ensure_ascii=False)

    async def run_task(self, task_prompt: str) -> str | object:
        await self.events.publish("reviewer", "Reviewer görevi alındı, kalite kontrolü başlıyor...")
        prompt = (task_prompt or "").strip()
        if not prompt:
            return "[UYARI] Boş reviewer görevi verildi."

        lower = prompt.lower()
        if lower.startswith("repo_info"):
            return str(await self.call_tool("repo_info", ""))
        if lower.startswith("list_prs"):
            arg = prompt.split("|", 1)[1].strip() if "|" in prompt else "open"
            return str(await self.call_tool("list_prs", arg))
        if lower.startswith("pr_diff|"):
            return str(await self.call_tool("pr_diff", prompt.split("|", 1)[1].strip()))
        if lower.startswith("list_issues"):
            arg = prompt.split("|", 1)[1].strip() if "|" in prompt else "open"
            return str(await self.call_tool("list_issues", arg))
        if lower.startswith("run_tests"):
            arg = (
                prompt.split("|", 1)[1].strip()
                if "|" in prompt
                else getattr(self.config, "REVIEWER_TEST_COMMAND", "python -m pytest")
            )
            return str(await self.call_tool("run_tests", arg))
        if lower.startswith("lsp_diagnostics"):
            arg = prompt.split("|", 1)[1].strip() if "|" in prompt else ""
            return str(await self.call_tool("lsp_diagnostics", arg))
        if lower.startswith("graph_impact"):
            arg = prompt.split("|", 1)[1].strip() if "|" in prompt else ""
            return str(await self.call_tool("graph_impact", arg))

        if lower.startswith("review_code|"):
            payload = self._parse_review_payload(prompt.split("|", 1)[1].strip())
            context = str(payload.get("review_context", "") or "").strip()
            await self.events.publish("reviewer", "LLM tabanlı dinamik QA testleri üretiliyor...")
            dynamic_test_output = await self._run_dynamic_tests(context)

            await self.events.publish("reviewer", "Regresyon test planı hazırlanıyor...")
            regression_chunks = []
            for command in self._build_regression_commands(context):
                await self.events.publish(
                    "reviewer", f"Sandbox içinde test çalıştırılıyor: {command}"
                )
                regression_chunks.append(await self.call_tool("run_tests", command))
            regression_output = "\n\n".join(regression_chunks)

            await self.events.publish("reviewer", "GraphRAG etki analizi hazırlanıyor...")
            graph_output = await self.call_tool("graph_impact", context)
            graph_payload: dict[str, object] = {
                "status": "tool-error",
                "summary": "GraphRAG çıktısı çözümlenemedi.",
                "reports": [],
            }
            with contextlib.suppress(json.JSONDecodeError):
                parsed_graph = json.loads(graph_output)
                if isinstance(parsed_graph, dict):
                    graph_payload = parsed_graph
            graph_summary = self._summarize_graph_payload(graph_payload)

            browser_output = await self.call_tool(
                "browser_signals", json.dumps(payload, ensure_ascii=False)
            )
            browser_payload: dict[str, object] = {
                "status": "no-signal",
                "risk": "düşük",
                "summary": "Browser sinyali alınamadı.",
            }
            with contextlib.suppress(json.JSONDecodeError):
                parsed_browser = json.loads(browser_output)
                if isinstance(parsed_browser, dict):
                    browser_payload = parsed_browser
            browser_summary = self._summarize_browser_signals(browser_payload)

            followup_paths = ReviewerAgent._as_str_list(graph_summary.get("followup_paths", []))
            lsp_scope_paths = self._merge_candidate_paths(
                self._build_lsp_candidate_paths(context),
                followup_paths,
            )
            await self.events.publish(
                "reviewer",
                f"LSP tabanlı semantik denetim çalıştırılıyor... hedef={len(lsp_scope_paths) or 1}",
            )
            lsp_output = await self.call_tool("lsp_diagnostics", " ".join(lsp_scope_paths))
            semantic_report = self._summarize_lsp_diagnostics(lsp_output)
            combined_impact = self._build_combined_impact_report(
                semantic_report,
                graph_summary,
                self._build_lsp_candidate_paths(context),
                lsp_scope_paths or ["workspace:auto"],
            )
            fix_recommendations = self._build_fix_recommendations(
                semantic_report,
                graph_payload,
                combined_impact,
            )
            fix_recommendations.extend(self._build_browser_fix_recommendations(browser_summary))
            regression_commands = self._build_regression_commands(context)
            remediation_loop = self._build_remediation_loop(
                semantic_report,
                graph_summary,
                combined_impact,
                fix_recommendations,
                regression_commands,
            )

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
            elif browser_summary["risk"] in {"orta", "yüksek"}:
                risk = str(browser_summary["risk"])
            if combined_impact["impact_level"] in {"high", "critical"} and risk == "düşük":
                risk = "orta"
            if browser_summary["status"] == "failed":
                status = "FAIL"
                decision = "REJECT"
                risk = "yüksek"

            await self.events.publish("reviewer", "QA kararı coder ajanına P2P ile iletiliyor...")
            feedback_payload = json.dumps(
                {
                    "decision": decision,
                    "risk": risk,
                    "summary": (
                        f"[REVIEW:{status}] Dinamik + regresyon + LSP semantik denetimleri değerlendirildi. "
                        f"{semantic_report['summary']} {graph_summary['summary']} "
                        f"{browser_summary['summary']} {combined_impact['summary']}"
                    ),
                    "dynamic_test_output": dynamic_test_output,
                    "regression_test_output": regression_output,
                    "lsp_diagnostics_output": lsp_output,
                    "semantic_risk_report": semantic_report,
                    "graph_impact_output": graph_output,
                    "graph_impact_report": graph_payload,
                    "graph_review_scope": graph_summary,
                    "browser_signals_output": browser_output,
                    "browser_signals_report": browser_payload,
                    "browser_signal_summary": browser_summary,
                    "combined_impact_report": combined_impact,
                    "fix_recommendations": fix_recommendations,
                    "remediation_loop": remediation_loop,
                    "lsp_scope_paths": lsp_scope_paths or ["workspace:auto"],
                },
                ensure_ascii=False,
            )
            return self.delegate_to(
                "coder", f"qa_feedback|{feedback_payload}", reason="review_decision"
            )

        if any(k in lower for k in ("review", "incele", "regresyon", "test")):
            return await self.run_task("review_code|Doğal dil inceleme isteği")

        return str(await self.call_tool("list_prs", "open"))
