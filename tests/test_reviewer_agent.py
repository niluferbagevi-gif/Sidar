import asyncio
import json

from agent.core.contracts import is_delegation_request
from agent.roles.reviewer_agent import ReviewerAgent


def test_reviewer_agent_initializes_expected_tools():
    a = ReviewerAgent()
    assert set(a.tools.keys()) == {"repo_info", "list_prs", "pr_diff", "list_issues", "run_tests", "lsp_diagnostics", "graph_impact"}
    assert hasattr(a, "code")


def test_reviewer_extracts_changed_paths_safely():
    a = ReviewerAgent()
    paths = a._extract_changed_paths("diff: tests/test_a.py core/db.py ../etc/passwd /tmp/x.py")
    assert "tests/test_a.py" in paths
    assert "core/db.py" in paths
    assert all(".." not in p for p in paths)
    assert all(not p.startswith("/") for p in paths)


def test_reviewer_builds_targeted_plus_regression_commands():
    a = ReviewerAgent()
    cmds = a._build_regression_commands("changed tests/test_reviewer_agent.py and core/db.py")
    assert cmds[0].startswith("pytest -q tests/test_reviewer_agent.py")
    assert any(c == a.cfg.REVIEWER_TEST_COMMAND for c in cmds)


def test_reviewer_builds_lsp_candidate_paths():
    a = ReviewerAgent()
    paths = a._build_lsp_candidate_paths(
        "changed agent/roles/reviewer_agent.py web_ui_react/src/App.jsx docs/README.md core/db.py"
    )
    assert paths == ["agent/roles/reviewer_agent.py", "web_ui_react/src/App.jsx", "core/db.py"]


def test_reviewer_builds_graph_candidate_paths():
    a = ReviewerAgent()
    paths = a._build_graph_candidate_paths(
        "changed agent/roles/reviewer_agent.py docs/README.md web_ui_react/src/App.jsx core/db.py"
    )
    assert paths == ["agent/roles/reviewer_agent.py", "web_ui_react/src/App.jsx", "core/db.py"]


def test_reviewer_collects_graph_followup_paths_from_structured_payload():
    payload = {
        "status": "ok",
        "reports": [
            {
                "target": "core/db.py",
                "ok": True,
                "details": {
                    "review_targets": ["core/db.py", "agent/roles/reviewer_agent.py"],
                    "impacted_endpoint_handlers": ["web_server.py"],
                    "caller_files": ["web_ui_react/src/App.jsx"],
                    "direct_dependents": ["README.md", "core/db.py"],
                },
            }
        ],
    }

    paths = ReviewerAgent._collect_graph_followup_paths(payload)

    assert paths == [
        "core/db.py",
        "agent/roles/reviewer_agent.py",
        "web_server.py",
        "web_ui_react/src/App.jsx",
    ]


def test_reviewer_summarize_graph_payload_marks_high_risk():
    summary = ReviewerAgent._summarize_graph_payload(
        {
            "status": "ok",
            "summary": "GraphRAG etki analizi 1 hedef için üretildi.",
            "reports": [
                {
                    "target": "core/db.py",
                    "ok": True,
                    "details": {
                        "risk_level": "high",
                        "review_targets": ["core/db.py", "web_server.py"],
                        "impacted_endpoint_handlers": ["web_server.py"],
                        "caller_files": [],
                        "direct_dependents": [],
                        "impacted_endpoints": ["endpoint:GET /health"],
                    },
                }
            ],
        }
    )

    assert summary["risk"] == "orta"
    assert summary["high_risk_targets"] == ["core/db.py"]
    assert "web_server.py" in summary["followup_paths"]


def test_reviewer_summarize_lsp_diagnostics_rejects_errors():
    summary = ReviewerAgent._summarize_lsp_diagnostics(
        "[LSP:OK] hedefler=core/db.py\n"
        "[OUTPUT]\n"
        "- /workspace/Sidar/core/db.py: satır 1, sütun 1 | severity=1 | name is not defined\n"
        "- /workspace/Sidar/core/db.py: satır 2, sütun 4 | severity=2 | type mismatch"
    )
    assert summary["decision"] == "REJECT"
    assert summary["risk"] == "yüksek"
    assert summary["counts"] == {1: 1, 2: 1}


def test_reviewer_build_combined_impact_report_detects_indirect_breakage():
    semantic_report = {
        "status": "issues-found",
        "risk": "yüksek",
        "decision": "REJECT",
        "counts": {1: 1},
        "issues": [
            {
                "path": "/workspace/Sidar/web_server.py",
                "line": 12,
                "character": 4,
                "severity": 1,
                "message": "name is not defined",
            }
        ],
        "summary": "LSP semantik denetimi 1 bulgu üretti.",
    }
    graph_summary = {
        "status": "ok",
        "risk": "orta",
        "high_risk_targets": ["core/db.py"],
        "followup_paths": ["web_server.py", "web_ui_react/src/App.jsx"],
        "summary": "GraphRAG 1 hedefi analiz etti.",
    }

    combined = ReviewerAgent._build_combined_impact_report(
        semantic_report,
        graph_summary,
        ["core/db.py"],
        ["core/db.py", "web_server.py"],
    )

    assert combined["impact_level"] == "critical"
    assert combined["indirect_breakage_paths"] == ["web_server.py"]
    assert combined["high_risk_targets"] == ["core/db.py"]


def test_reviewer_build_fix_recommendations_prioritizes_graph_semantic_overlap():
    semantic_report = {
        "issues": [
            {
                "path": "/workspace/Sidar/web_server.py",
                "severity": 1,
                "message": "name is not defined",
            }
        ]
    }
    graph_payload = {
        "reports": [
            {
                "target": "core/db.py",
                "ok": True,
                "details": {
                    "review_targets": ["core/db.py", "web_server.py"],
                    "impacted_endpoint_handlers": ["web_server.py"],
                    "caller_files": [],
                    "direct_dependents": [],
                    "impacted_endpoints": ["endpoint:GET /health"],
                },
            }
        ]
    }
    combined_impact = {
        "indirect_breakage_paths": ["web_server.py"],
    }

    recommendations = ReviewerAgent._build_fix_recommendations(
        semantic_report,
        graph_payload,
        combined_impact,
    )

    assert recommendations[0]["path"] == "web_server.py"
    assert recommendations[0]["reason"] == "graph+semantic"
    assert "endpoint:GET /health" in recommendations[0]["related_endpoints"]


def test_reviewer_lsp_diagnostics_tool_uses_code_manager(monkeypatch):
    a = ReviewerAgent()

    def fake_lsp_semantic_audit(paths=None):
        assert paths == ["core/db.py", "web_ui_react/src/App.jsx"]
        return True, {
            "status": "clean",
            "risk": "düşük",
            "decision": "APPROVE",
            "counts": {},
            "issues": [],
            "summary": "LSP diagnostics temiz.",
        }

    monkeypatch.setattr(a.code, "lsp_semantic_audit", fake_lsp_semantic_audit)
    out = asyncio.run(a.call_tool("lsp_diagnostics", "core/db.py web_ui_react/src/App.jsx README.md"))
    payload = json.loads(out)
    assert payload["status"] == "clean"
    assert payload["summary"] == "LSP diagnostics temiz."


def test_reviewer_graph_impact_tool_uses_graph_store(monkeypatch):
    a = ReviewerAgent()

    class _FakeDocs:
        def graph_impact_details(self, target, top_k=10):
            assert top_k == 8
            return True, {
                "target": target,
                "risk_level": "high",
                "review_targets": [target, "web_server.py"],
                "impacted_endpoint_handlers": ["web_server.py"],
                "caller_files": [],
                "direct_dependents": [],
                "impacted_endpoints": ["endpoint:GET /health"],
            }

        def analyze_graph_impact(self, target, top_k=10):
            assert top_k == 8
            return True, f"[GraphRAG Impact] {target}"

    monkeypatch.setattr(a, "_get_graph_store", lambda: _FakeDocs())
    out = asyncio.run(a.call_tool("graph_impact", "core/db.py docs/README.md web_ui_react/src/App.jsx"))
    payload = json.loads(out)
    assert payload["status"] == "ok"
    assert payload["targets"] == ["core/db.py", "web_ui_react/src/App.jsx"]
    assert payload["reports"][0]["report"].startswith("[GraphRAG Impact]")
    assert payload["reports"][0]["details"]["risk_level"] == "high"


def test_reviewer_build_dynamic_test_content_uses_llm(monkeypatch):
    a = ReviewerAgent()

    async def fake_call_llm(messages, **kwargs):
        assert "add_two" in messages[0]["content"]
        assert kwargs["system_prompt"] == a.TEST_GENERATION_PROMPT
        return "```python\ndef test_generated():\n    assert 2 + 2 == 4\n```"

    monkeypatch.setattr(a, "call_llm", fake_call_llm)
    out = asyncio.run(a._build_dynamic_test_content("function add_two(x): return x + 2"))
    assert "def test_generated" in out


def test_reviewer_agent_run_tests_tool_rejects_unsafe_command():
    a = ReviewerAgent()
    out = asyncio.run(a.call_tool("run_tests", "rm -rf /"))
    assert "Kullanım" in out


def test_reviewer_agent_run_tests_uses_code_manager_sandbox_runner(monkeypatch):
    a = ReviewerAgent()

    def fake_run_shell_in_sandbox(command: str, cwd=None):
        assert command == "pytest -q tests/test_reviewer_agent.py"
        assert cwd == str(a.cfg.BASE_DIR)
        return True, "ok"

    def fail_if_called(*_args, **_kwargs):
        raise AssertionError("run_shell should not be used for reviewer sandbox tests")

    monkeypatch.setattr(a.code, "run_shell_in_sandbox", fake_run_shell_in_sandbox)
    monkeypatch.setattr(a.code, "run_shell", fail_if_called)
    out = asyncio.run(a.call_tool("run_tests", "pytest -q tests/test_reviewer_agent.py"))
    assert "[TEST:OK]" in out
    assert "Docker CLI sandbox" in out


def test_reviewer_agent_run_tests_fail_closed_when_sandbox_runner_fails(monkeypatch):
    a = ReviewerAgent()

    def fake_run_shell_in_sandbox(command: str, cwd=None):
        assert command == "pytest -q tests/test_reviewer_agent.py"
        return False, "Docker CLI bulunamadı"

    monkeypatch.setattr(a.code, "run_shell_in_sandbox", fake_run_shell_in_sandbox)
    out = asyncio.run(a.call_tool("run_tests", "pytest -q tests/test_reviewer_agent.py"))
    assert "FAIL-CLOSED" in out
    assert "Docker CLI bulunamadı" in out


def test_reviewer_review_code_returns_p2p_feedback(monkeypatch):
    a = ReviewerAgent()

    async def fake_dynamic(_ctx: str) -> str:
        return "[TEST:OK] dynamic"

    calls = []

    async def fake_run_tests(arg: str) -> str:
        calls.append(arg)
        return f"[TEST:OK] {arg}"

    monkeypatch.setattr(a, "_run_dynamic_tests", fake_dynamic)
    a.tools["run_tests"] = fake_run_tests
    a.tools["lsp_diagnostics"] = lambda _arg: asyncio.sleep(0, result=json.dumps({
        "status": "clean",
        "risk": "düşük",
        "decision": "APPROVE",
        "counts": {},
        "issues": [],
        "summary": "LSP diagnostics temiz.",
    }, ensure_ascii=False))
    a.tools["graph_impact"] = lambda _arg: asyncio.sleep(0, result=json.dumps({
        "status": "ok",
        "summary": "GraphRAG etki analizi 1 hedef için üretildi.",
        "targets": ["tests/test_reviewer_agent.py"],
        "reports": [{"target": "tests/test_reviewer_agent.py", "ok": True, "report": "[GraphRAG Impact] tests/test_reviewer_agent.py"}],
    }, ensure_ascii=False))

    out = asyncio.run(a.run_task("review_code|tests/test_reviewer_agent.py"))
    assert is_delegation_request(out)
    assert out.target_agent == "coder"
    assert out.payload.startswith("qa_feedback|")
    payload = json.loads(out.payload.split("|", 1)[1])
    assert payload["decision"] == "APPROVE"
    assert payload["semantic_risk_report"]["status"] == "clean"
    assert payload["graph_impact_report"]["status"] == "ok"
    assert "tests/test_reviewer_agent.py" in payload["lsp_scope_paths"]
    assert any(c.startswith("pytest -q tests/test_reviewer_agent.py") for c in calls)
    assert any(c == a.cfg.REVIEWER_TEST_COMMAND for c in calls)


def test_reviewer_review_code_rejects_on_fail_closed(monkeypatch):
    a = ReviewerAgent()

    async def fake_dynamic(_ctx: str) -> str:
        return "[TEST:FAIL-CLOSED] komut=dynamic"

    async def fake_run_tests(arg: str) -> str:
        return f"[TEST:OK] {arg}"

    monkeypatch.setattr(a, "_run_dynamic_tests", fake_dynamic)
    a.tools["run_tests"] = fake_run_tests
    a.tools["lsp_diagnostics"] = lambda _arg: asyncio.sleep(0, result=json.dumps({
        "status": "clean",
        "risk": "düşük",
        "decision": "APPROVE",
        "counts": {},
        "issues": [],
        "summary": "LSP diagnostics temiz.",
    }, ensure_ascii=False))
    a.tools["graph_impact"] = lambda _arg: asyncio.sleep(0, result=json.dumps({
        "status": "ok",
        "summary": "GraphRAG etki analizi 1 hedef için üretildi.",
        "targets": ["core/db.py"],
        "reports": [{"target": "core/db.py", "ok": True, "report": "[GraphRAG Impact] core/db.py"}],
    }, ensure_ascii=False))

    out = asyncio.run(a.run_task("review_code|core/db.py"))
    payload = json.loads(out.payload.split("|", 1)[1])
    assert payload["decision"] == "REJECT"
    assert payload["risk"] == "yüksek"


def test_reviewer_review_code_rejects_on_lsp_semantic_error(monkeypatch):
    a = ReviewerAgent()

    async def fake_dynamic(_ctx: str) -> str:
        return "[TEST:OK] dynamic"

    async def fake_run_tests(arg: str) -> str:
        return f"[TEST:OK] {arg}"

    async def fake_lsp(_arg: str) -> str:
        return json.dumps({
            "status": "issues-found",
            "risk": "yüksek",
            "decision": "REJECT",
            "counts": {1: 1},
            "issues": [{"path": "/workspace/Sidar/core/db.py", "line": 1, "character": 1, "severity": 1, "message": "name is not defined"}],
            "summary": "LSP semantik denetimi 1 bulgu üretti (error=1, warning=0, info=0).",
        }, ensure_ascii=False)

    monkeypatch.setattr(a, "_run_dynamic_tests", fake_dynamic)
    a.tools["run_tests"] = fake_run_tests
    a.tools["lsp_diagnostics"] = fake_lsp
    a.tools["graph_impact"] = lambda _arg: asyncio.sleep(0, result=json.dumps({
        "status": "ok",
        "summary": "GraphRAG etki analizi 1 hedef için üretildi.",
        "targets": ["core/db.py"],
        "reports": [{"target": "core/db.py", "ok": True, "report": "[GraphRAG Impact] core/db.py"}],
    }, ensure_ascii=False))

    out = asyncio.run(a.run_task("review_code|core/db.py"))
    payload = json.loads(out.payload.split("|", 1)[1])
    assert payload["decision"] == "REJECT"
    assert payload["semantic_risk_report"]["risk"] == "yüksek"
    assert "LSP semantik denetimi" in payload["summary"]


def test_reviewer_review_code_escalates_risk_from_graph_scope(monkeypatch):
    a = ReviewerAgent()

    async def fake_dynamic(_ctx: str) -> str:
        return "[TEST:OK] dynamic"

    async def fake_run_tests(arg: str) -> str:
        return f"[TEST:OK] {arg}"

    captured_args = []

    async def fake_lsp(arg: str) -> str:
        captured_args.append(arg)
        return json.dumps({
            "status": "clean",
            "risk": "düşük",
            "decision": "APPROVE",
            "counts": {},
            "issues": [],
            "summary": "LSP diagnostics temiz.",
        }, ensure_ascii=False)

    monkeypatch.setattr(a, "_run_dynamic_tests", fake_dynamic)
    a.tools["run_tests"] = fake_run_tests
    a.tools["lsp_diagnostics"] = fake_lsp
    a.tools["graph_impact"] = lambda _arg: asyncio.sleep(0, result=json.dumps({
        "status": "ok",
        "summary": "GraphRAG etki analizi 1 hedef için üretildi.",
        "targets": ["core/db.py"],
        "reports": [{
            "target": "core/db.py",
            "ok": True,
            "report": "[GraphRAG Impact] core/db.py",
            "details": {
                "risk_level": "high",
                "review_targets": ["core/db.py", "web_server.py"],
                "impacted_endpoint_handlers": ["web_server.py"],
                "caller_files": ["web_ui_react/src/App.jsx"],
                "direct_dependents": [],
                "impacted_endpoints": ["endpoint:GET /health"],
            },
        }],
    }, ensure_ascii=False))

    out = asyncio.run(a.run_task("review_code|core/db.py"))
    payload = json.loads(out.payload.split("|", 1)[1])
    assert payload["decision"] == "APPROVE"
    assert payload["risk"] == "orta"
    assert payload["graph_review_scope"]["risk"] == "orta"
    assert payload["combined_impact_report"]["impact_level"] == "high"
    assert payload["fix_recommendations"][0]["path"] == "web_server.py"
    assert "web_server.py" in payload["lsp_scope_paths"]
    assert "web_ui_react/src/App.jsx" in payload["lsp_scope_paths"]
    assert captured_args and "web_server.py" in captured_args[0]


def test_reviewer_review_code_flags_indirect_breakage_from_graph_plus_lsp(monkeypatch):
    a = ReviewerAgent()

    async def fake_dynamic(_ctx: str) -> str:
        return "[TEST:OK] dynamic"

    async def fake_run_tests(arg: str) -> str:
        return f"[TEST:OK] {arg}"

    async def fake_lsp(_arg: str) -> str:
        return json.dumps({
            "status": "issues-found",
            "risk": "yüksek",
            "decision": "REJECT",
            "counts": {1: 1},
            "issues": [
                {
                    "path": "/workspace/Sidar/web_server.py",
                    "line": 5,
                    "character": 2,
                    "severity": 1,
                    "message": "Cannot access member",
                }
            ],
            "summary": "LSP semantik denetimi 1 bulgu üretti (error=1, warning=0, info=0).",
        }, ensure_ascii=False)

    monkeypatch.setattr(a, "_run_dynamic_tests", fake_dynamic)
    a.tools["run_tests"] = fake_run_tests
    a.tools["lsp_diagnostics"] = fake_lsp
    a.tools["graph_impact"] = lambda _arg: asyncio.sleep(0, result=json.dumps({
        "status": "ok",
        "summary": "GraphRAG etki analizi 1 hedef için üretildi.",
        "targets": ["core/db.py"],
        "reports": [{
            "target": "core/db.py",
            "ok": True,
            "report": "[GraphRAG Impact] core/db.py",
            "details": {
                "risk_level": "high",
                "review_targets": ["core/db.py", "web_server.py"],
                "impacted_endpoint_handlers": ["web_server.py"],
                "caller_files": ["web_ui_react/src/App.jsx"],
                "direct_dependents": [],
                "impacted_endpoints": ["endpoint:GET /health"],
            },
        }],
    }, ensure_ascii=False))

    out = asyncio.run(a.run_task("review_code|core/db.py"))
    payload = json.loads(out.payload.split("|", 1)[1])
    assert payload["decision"] == "REJECT"
    assert payload["combined_impact_report"]["indirect_breakage_paths"] == ["web_server.py"]
    assert payload["fix_recommendations"][0]["path"] == "web_server.py"
    assert payload["fix_recommendations"][0]["reason"] == "graph+semantic"

def test_reviewer_build_remediation_loop_marks_hitl_for_indirect_breakage():
    semantic_report = {
        "summary": "LSP semantik denetimi 1 bulgu üretti.",
        "counts": {1: 1},
    }
    graph_summary = {
        "risk": "orta",
        "summary": "GraphRAG 1 hedefi analiz etti.",
    }
    combined_impact = {
        "impact_level": "critical",
        "direct_scope_paths": ["core/db.py"],
        "graph_followup_paths": ["web_server.py"],
        "issue_paths": ["web_server.py"],
        "indirect_breakage_paths": ["web_server.py"],
    }
    fix_recommendations = [
        {
            "path": "web_server.py",
            "reason": "graph+semantic",
            "action": "Düzelt",
        }
    ]

    loop = ReviewerAgent._build_remediation_loop(
        semantic_report,
        graph_summary,
        combined_impact,
        fix_recommendations,
        ["pytest -q tests/test_reviewer_agent.py"],
    )

    assert loop["status"] == "planned"
    assert loop["mode"] == "self_heal_with_hitl"
    assert loop["needs_human_approval"] is True
    assert "web_server.py" in loop["scope_paths"]
    assert "semantic_issues" in loop["blocked_by"]
    assert loop["validation_commands"][0] == "pytest -q tests/test_reviewer_agent.py"