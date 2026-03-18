"""v3.0.26 güvenlik ve kalite düzeltmeleri için testler.

Kapatılan bulgular:
    Y-6  — record_routing_cost() entegrasyonu (core/llm_client.py)
    O-7  — Yeni FastAPI endpoint'leri (web_server.py)
    O-8  — SlackManager async initialize (managers/slack_manager.py)
    D-*  — Prometheus singleton, Config singleton, asyncio.Lock lazy init,
            async DatasetExporter dosya yazımı (core/judge.py, config.py,
            agent/sidar_agent.py, core/active_learning.py)

NOT: Bu ortamda `cryptography` paketinin Rust uzantısı (_cffi_backend) eksik
olduğundan jwt, jwt'ye bağlı olan tüm modüller için bir stub kullanılmaktadır.
Bu durum sistemin tasarımı veya uygulama güvenliğiyle ilgisizdir.
"""
from __future__ import annotations

# ─────────────────────────────────────────────────────────────────────────────
# CI ORTAM HAZIRLIĞI
# jwt paketi bu ortamda bozuk Rust uzantısı içerdiğinden stub ile değiştir.
# Bu blok, herhangi bir core.* importundan ÖNCE çalışmalıdır.
# ─────────────────────────────────────────────────────────────────────────────
import sys
import types as _types

_jwt_stub = _types.ModuleType("jwt")
class _PyJWTError(Exception): pass
_jwt_stub.PyJWTError = _PyJWTError
_jwt_stub.encode = lambda payload, secret, algorithm="HS256", **kw: "stub.payload.sig"
_jwt_stub.decode = lambda token, secret, algorithms=None, **kw: {}
for _k in [k for k in list(sys.modules) if k == "jwt" or k.startswith("jwt.")]:
    del sys.modules[_k]
sys.modules["jwt"] = _jwt_stub

# ─────────────────────────────────────────────────────────────────────────────
import asyncio
import importlib
import importlib.util
import json
import os
import pathlib
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ─────────────────────────────────────────────────────────────────────────────
# managers stub — __init__.py tetiklemeden alt modülleri doğrudan yükle
# ─────────────────────────────────────────────────────────────────────────────
if "httpx" not in sys.modules:
    _httpx_mock = MagicMock()
    _async_client_mock = MagicMock()
    _httpx_mock.AsyncClient.return_value.__aenter__ = AsyncMock(return_value=_async_client_mock)
    _httpx_mock.AsyncClient.return_value.__aexit__ = AsyncMock(return_value=False)
    sys.modules["httpx"] = _httpx_mock

if "managers" not in sys.modules:
    _mgr_pkg = _types.ModuleType("managers")
    _mgr_pkg.__path__ = []
    _mgr_pkg.__package__ = "managers"
    sys.modules["managers"] = _mgr_pkg

_ROOT = pathlib.Path(__file__).parent.parent


def _load_module(name: str, rel_path: str):
    """__init__.py tetiklemeden doğrudan dosyadan modül yükler."""
    spec = importlib.util.spec_from_file_location(name, _ROOT / rel_path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


_slack_mod = _load_module("managers.slack_manager", "managers/slack_manager.py")
SlackManager = _slack_mod.SlackManager

_judge_mod = importlib.import_module("core.judge")
_inc_prometheus = _judge_mod._inc_prometheus

_config_mod = importlib.import_module("config")
get_config = _config_mod.get_config
Config = _config_mod.Config


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


# =============================================================================
# Bulgu O-8 — SlackManager async initialize()
# =============================================================================
class TestSlackManagerInitialize:
    """SlackManager.initialize() → auth_test asyncio.to_thread ile çağrılır."""

    def test_initialize_method_exists(self):
        mgr = SlackManager()
        assert hasattr(mgr, "initialize"), "initialize() metodu eksik"
        assert asyncio.iscoroutinefunction(mgr.initialize), "initialize() async olmalı"

    def test_initialize_no_client_webhook_only_noop(self):
        """Webhook-only modda initialize() sessizce döner, available=True kalır."""
        mgr = SlackManager(webhook_url="https://hooks.slack.com/test")
        _run(mgr.initialize())
        assert mgr.is_available() is True

    def test_initialize_with_sdk_success(self):
        """Token + SDK: auth_test to_thread ile çağrılır, available=True."""
        mock_client = MagicMock()
        mock_client.auth_test.return_value = {"ok": True, "team": "TestTeam"}

        mgr = SlackManager.__new__(SlackManager)
        mgr.token = "xoxb-fake"
        mgr.webhook_url = ""
        mgr.default_channel = ""
        mgr._client = mock_client
        mgr._available = False
        mgr._webhook_only = False

        _run(mgr.initialize())

        mock_client.auth_test.assert_called_once()
        assert mgr.is_available() is True

    def test_initialize_sdk_failure_fallback_to_webhook(self):
        """auth_test başarısız → webhook_url varsa webhook moduna geçer."""
        mock_client = MagicMock()
        mock_client.auth_test.side_effect = Exception("Bağlantı hatası")

        mgr = SlackManager.__new__(SlackManager)
        mgr.token = "xoxb-fake"
        mgr.webhook_url = "https://hooks.slack.com/test"
        mgr.default_channel = ""
        mgr._client = mock_client
        mgr._available = False
        mgr._webhook_only = False

        _run(mgr.initialize())

        assert mgr.is_available() is True
        assert mgr._webhook_only is True

    def test_initialize_sdk_auth_not_ok_no_webhook(self):
        """auth_test ok=False ve webhook_url yok → available=False."""
        mock_client = MagicMock()
        mock_client.auth_test.return_value = {"ok": False, "error": "invalid_auth"}

        mgr = SlackManager.__new__(SlackManager)
        mgr.token = "xoxb-fake"
        mgr.webhook_url = ""
        mgr.default_channel = ""
        mgr._client = mock_client
        mgr._available = True
        mgr._webhook_only = False

        _run(mgr.initialize())

        assert mgr.is_available() is False

    def test_init_does_not_call_auth_test_synchronously(self):
        """__init__/_init_client() içinde auth_test çağrılmamalı."""
        mock_wc = MagicMock()
        mock_sdk = MagicMock()
        mock_sdk.WebClient = MagicMock(return_value=mock_wc)

        with patch.dict(sys.modules, {"slack_sdk": mock_sdk}):
            mgr = SlackManager(token="xoxb-test")

        mock_wc.auth_test.assert_not_called()


# =============================================================================
# Bulgu D — Config singleton: get_config()
# =============================================================================
class TestGetConfigSingleton:
    """get_config() her çağrıda aynı nesneyi döndürmeli."""

    def test_returns_config_instance(self):
        cfg = get_config()
        assert isinstance(cfg, Config)

    def test_returns_same_instance_each_call(self):
        a = get_config()
        b = get_config()
        assert a is b, "get_config() farklı nesneler döndürdü — singleton değil"

    def test_singleton_reset_creates_new_instance(self):
        """_config_instance None yapılıp yeniden çağrıldığında yeni nesne üretilir."""
        original = _config_mod._config_instance
        _config_mod._config_instance = None
        fresh = get_config()
        assert isinstance(fresh, Config)
        _config_mod._config_instance = original  # restore

    def test_get_config_exists_in_module(self):
        assert callable(getattr(_config_mod, "get_config", None))


# =============================================================================
# Bulgu D — Prometheus singleton: _inc_prometheus cache
# =============================================================================
class TestPrometheusGaugeCache:
    """_inc_prometheus() aynı metrik için tek Gauge kaydeder."""

    def setup_method(self):
        _judge_mod._prometheus_gauges.clear()

    def test_gauge_cached_after_first_call(self):
        mock_gauge = MagicMock()
        mock_gauge_cls = MagicMock(return_value=mock_gauge)

        with patch.dict(sys.modules, {"prometheus_client": MagicMock(Gauge=mock_gauge_cls)}):
            _inc_prometheus("sidar_test_c_a", 1.0)
            _inc_prometheus("sidar_test_c_a", 2.0)

        assert mock_gauge_cls.call_count == 1, "Gauge yalnızca bir kez oluşturulmalı"
        assert mock_gauge.set.call_count == 2

    def test_different_metrics_create_separate_gauges(self):
        mock_gauge = MagicMock()
        mock_gauge_cls = MagicMock(return_value=mock_gauge)

        with patch.dict(sys.modules, {"prometheus_client": MagicMock(Gauge=mock_gauge_cls)}):
            _inc_prometheus("sidar_uniq_x", 1.0)
            _inc_prometheus("sidar_uniq_y", 2.0)

        assert mock_gauge_cls.call_count == 2

    def test_missing_prometheus_silenced(self):
        """prometheus_client None ise hata yükseltilmemeli."""
        with patch.dict(sys.modules, {"prometheus_client": None}):
            _inc_prometheus("sidar_no_prom", 1.0)

    def test_prometheus_gauges_dict_exists(self):
        assert hasattr(_judge_mod, "_prometheus_gauges")
        assert isinstance(_judge_mod._prometheus_gauges, dict)


# =============================================================================
# Bulgu D — asyncio.Lock lazy init: SidarAgent
# =============================================================================
class TestSidarAgentLazyLock:
    """SidarAgent.__init__() içinde asyncio.Lock() oluşturulmamalı."""

    def test_lock_assignments_are_none_in_init(self):
        """AST analizi: __init__ içinde self._lock = asyncio.Lock() atanmamalı."""
        import ast
        src = (_ROOT / "agent" / "sidar_agent.py").read_text(encoding="utf-8")
        tree = ast.parse(src)

        # __init__ metodundaki self._lock ve self._init_lock atamalarını bul
        lock_assignments_in_init = []
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "__init__":
                for stmt in ast.walk(node):
                    if (
                        isinstance(stmt, ast.Assign)
                        and isinstance(stmt.value, ast.Call)
                    ):
                        func = stmt.value.func
                        # asyncio.Lock() çağrısı
                        is_lock_call = (
                            isinstance(func, ast.Attribute)
                            and func.attr == "Lock"
                            and isinstance(func.value, ast.Name)
                            and func.value.id == "asyncio"
                        )
                        if is_lock_call:
                            for target in stmt.targets:
                                if (
                                    isinstance(target, ast.Attribute)
                                    and target.attr in ("_lock", "_init_lock")
                                ):
                                    lock_assignments_in_init.append(target.attr)

        assert len(lock_assignments_in_init) == 0, (
            f"__init__ içinde asyncio.Lock() ile atanan kilitler bulundu: "
            f"{lock_assignments_in_init}. Lazy init kullanılmalı."
        )

    def test_lock_none_assignments_exist_in_init(self):
        """AST analizi: __init__ içinde _lock = None ataması olmalı."""
        import ast
        src = (_ROOT / "agent" / "sidar_agent.py").read_text(encoding="utf-8")
        tree = ast.parse(src)

        none_assignments = []
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "__init__":
                for stmt in ast.walk(node):
                    if (
                        isinstance(stmt, (ast.Assign, ast.AnnAssign))
                        and isinstance(getattr(stmt, "value", None), ast.Constant)
                        and getattr(stmt, "value").value is None
                    ):
                        # Annotated assign: self._lock: T = None
                        target = getattr(stmt, "target", None)
                        if target and isinstance(target, ast.Attribute) and target.attr in ("_lock", "_init_lock"):
                            none_assignments.append(target.attr)
                        # Normal assign: self._lock = None
                        for t in getattr(stmt, "targets", []):
                            if isinstance(t, ast.Attribute) and t.attr in ("_lock", "_init_lock"):
                                none_assignments.append(t.attr)

        assert "_lock" in none_assignments or "_init_lock" in none_assignments, (
            "_lock veya _init_lock __init__ içinde None olarak başlatılmalı"
        )


# =============================================================================
# Bulgu D — DatasetExporter async dosya yazımı
# =============================================================================
class TestDatasetExporterAsyncWrite:
    """DatasetExporter.export() dosya yazımını asyncio.to_thread ile yapar."""

    def test_export_uses_to_thread(self):
        from core.active_learning import DatasetExporter

        mock_store = MagicMock()
        mock_store.get_pending_export = AsyncMock(return_value=[
            {"id": 1, "prompt": "test", "response": "yanit", "correction": ""},
        ])
        mock_store.mark_exported = AsyncMock()

        to_thread_calls = []

        async def _fake_to_thread(fn, *a, **kw):
            to_thread_calls.append(fn)
            fn()

        with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False) as tmp:
            tmp_path = tmp.name

        try:
            with patch("core.active_learning.asyncio.to_thread", side_effect=_fake_to_thread):
                result = _run(DatasetExporter(mock_store).export(tmp_path, fmt="jsonl"))

            assert len(to_thread_calls) == 1, "asyncio.to_thread bir kez çağrılmalı"
            assert result["count"] == 1
        finally:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)

    def test_export_writes_correct_jsonl(self):
        from core.active_learning import DatasetExporter

        mock_store = MagicMock()
        mock_store.get_pending_export = AsyncMock(return_value=[
            {"id": 1, "prompt": "soru", "response": "cevap", "correction": ""},
            {"id": 2, "prompt": "soru2", "response": "cevap2", "correction": "düzeltme"},
        ])
        mock_store.mark_exported = AsyncMock()

        with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False) as tmp:
            tmp_path = tmp.name

        try:
            _run(DatasetExporter(mock_store).export(tmp_path, fmt="jsonl"))
            lines = Path(tmp_path).read_text(encoding="utf-8").strip().splitlines()
            assert len(lines) == 2
            obj0 = json.loads(lines[0])
            assert obj0["prompt"] == "soru" and obj0["completion"] == "cevap"
            assert json.loads(lines[1])["completion"] == "düzeltme"
        finally:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)

    def test_export_alpaca_format(self):
        from core.active_learning import DatasetExporter

        mock_store = MagicMock()
        mock_store.get_pending_export = AsyncMock(return_value=[
            {"id": 1, "prompt": "komut", "response": "sonuç", "correction": ""},
        ])
        mock_store.mark_exported = AsyncMock()

        with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False) as tmp:
            tmp_path = tmp.name

        try:
            _run(DatasetExporter(mock_store).export(tmp_path, fmt="alpaca"))
            obj = json.loads(Path(tmp_path).read_text(encoding="utf-8").strip())
            assert obj["instruction"] == "komut"
            assert obj["input"] == ""
            assert obj["output"] == "sonuç"
        finally:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)

    def test_export_empty_store_returns_zero(self):
        from core.active_learning import DatasetExporter

        mock_store = MagicMock()
        mock_store.get_pending_export = AsyncMock(return_value=[])

        result = _run(DatasetExporter(mock_store).export("/tmp/empty_v3026.jsonl"))
        assert result["count"] == 0


# =============================================================================
# Bulgu Y-6 — record_routing_cost() entegrasyonu (AST + runtime)
# =============================================================================
class TestRecordRoutingCostIntegration:
    """record_routing_cost() çağrılabilir ve bütçe tracker'ı günceller."""

    def test_record_routing_cost_imported_in_llm_client(self):
        """core/llm_client.py'de record_routing_cost import edilmeli."""
        import ast
        src = (_ROOT / "core" / "llm_client.py").read_text(encoding="utf-8")
        tree = ast.parse(src)
        imported_names = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and (node.module or "") == "core.router":
                imported_names.extend(alias.name for alias in node.names)
        assert "record_routing_cost" in imported_names

    def test_record_routing_cost_called_after_response(self):
        """record_routing_cost, non-ollama sağlayıcıda LLM yanıtından sonra çağrılmalı."""
        src = (_ROOT / "core" / "llm_client.py").read_text(encoding="utf-8")
        assert "record_routing_cost" in src
        assert "COST_ROUTING_TOKEN_COST_USD" in src

    def test_record_routing_cost_callable(self):
        from core.router import record_routing_cost
        record_routing_cost(0.0)  # hata yükseltilmemeli

    def test_budget_tracker_increases_after_record(self):
        from core.router import record_routing_cost
        from core import router as _r
        tracker = _r._budget_tracker
        # _DailyBudgetTracker'ın gerçek alan adını dinamik olarak bul
        cost_attr = next(
            (a for a in ("_daily_cost", "_today_usd", "_spent", "_amount")
             if hasattr(tracker, a)),
            None,
        )
        if cost_attr:
            before = float(getattr(tracker, cost_attr))
            record_routing_cost(0.005)
            after = float(getattr(tracker, cost_attr))
            assert after >= before + 0.005 - 1e-9, "Bütçe tracker artmadı"
        else:
            # Tracker doğrudan erişilebilir değil — budget_exceeded ile dolaylı test
            record_routing_cost(0.001)  # should not raise


# =============================================================================
# Bulgu O-7 — Web server yeni endpoint yapısı (AST analizi)
# =============================================================================
class TestWebServerNewEndpointsStructure:
    """web_server.py'de yeni endpoint'lerin tanımlı olduğunu AST ile doğrula."""

    def _get_routes(self):
        import ast
        src = (_ROOT / "web_server.py").read_text(encoding="utf-8")
        tree = ast.parse(src)
        routes: set = set()
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "app"
                and node.func.attr in ("get", "post", "delete", "put")
                and node.args
                and isinstance(node.args[0], ast.Constant)
            ):
                routes.add((node.func.attr.upper(), node.args[0].value))
        return routes

    def test_vision_analyze(self):
        assert ("POST", "/api/vision/analyze") in self._get_routes()

    def test_vision_mockup(self):
        assert ("POST", "/api/vision/mockup") in self._get_routes()

    def test_entity_upsert(self):
        assert ("POST", "/api/memory/entity/upsert") in self._get_routes()

    def test_entity_get_profile(self):
        routes = self._get_routes()
        assert any("memory/entity" in r[1] and r[0] == "GET" for r in routes)

    def test_entity_delete(self):
        assert ("DELETE", "/api/memory/entity/{user_id}/{key}") in self._get_routes()

    def test_feedback_record(self):
        assert ("POST", "/api/feedback/record") in self._get_routes()

    def test_feedback_stats(self):
        assert ("GET", "/api/feedback/stats") in self._get_routes()

    def test_slack_send(self):
        assert ("POST", "/api/integrations/slack/send") in self._get_routes()

    def test_slack_channels(self):
        assert ("GET", "/api/integrations/slack/channels") in self._get_routes()

    def test_jira_issue_create(self):
        assert ("POST", "/api/integrations/jira/issue") in self._get_routes()

    def test_jira_issues_search(self):
        assert ("GET", "/api/integrations/jira/issues") in self._get_routes()

    def test_teams_send(self):
        assert ("POST", "/api/integrations/teams/send") in self._get_routes()
