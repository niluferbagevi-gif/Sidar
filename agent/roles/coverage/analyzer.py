"""Analysis-oriented CoverageAgent tool implementations."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agent.roles.coverage_agent import CoverageAgent


async def tool_run_pytest(agent: CoverageAgent, arg: str) -> str:
    payload = agent._parse_payload(arg)
    default_cmd = "pytest --cov=. --cov-report=xml --cov-report=term"
    command = str(payload.get("command", default_cmd) or default_cmd).strip()
    cwd = str(payload.get("cwd", agent.cfg.BASE_DIR) or agent.cfg.BASE_DIR)
    result = await agent._call_maybe_async(agent.code.run_pytest_and_collect, command, cwd)
    return json.dumps(result, ensure_ascii=False)


async def tool_analyze_pytest_output(agent: CoverageAgent, arg: str) -> str:
    payload = agent._parse_payload(arg)
    output = str(payload.get("output", arg) or arg)
    analysis = await agent._call_maybe_async(agent.code.analyze_pytest_output, output)
    return json.dumps(analysis, ensure_ascii=False)


async def tool_analyze_coverage_report(agent: CoverageAgent, arg: str) -> str:
    payload = agent._parse_payload(arg)
    coverage_xml_path = str(payload.get("coverage_xml", "coverage.xml") or "coverage.xml")
    coveragerc_path = str(payload.get("coveragerc", ".coveragerc") or ".coveragerc")
    terminal_output = str(payload.get("coverage_output", "") or "")
    limit_val = payload.get("limit")
    limit = int(limit_val) if limit_val is not None else 25
    coverage_analysis = agent._parse_coverage_xml(coverage_xml_path, limit=limit)
    terminal_analysis = agent._parse_terminal_coverage_output(terminal_output, limit=limit)
    coveragerc = agent._read_coveragerc(coveragerc_path)
    findings = list(coverage_analysis.get("findings", []) or [])
    if not findings:
        findings = list(terminal_analysis.get("findings", []) or [])
    return json.dumps(
        {
            "summary": coverage_analysis.get("summary", ""),
            "coverage_xml": coverage_analysis,
            "coverage_terminal": terminal_analysis,
            "coveragerc": coveragerc,
            "findings": findings,
        },
        ensure_ascii=False,
    )


async def tool_analyze_test_artifacts(agent: CoverageAgent, arg: str) -> str:
    """Legacy compatibility: map coverage/junit artifacts to coverage analysis format."""
    text = (arg or "").strip()
    if text.startswith(("{", "[")):
        payload = agent._parse_payload(text)
        if "coverage_xml" not in payload:
            payload["coverage_xml"] = ""
    else:
        payload = {"coverage_xml": text}
    return await agent._tool_analyze_coverage_report(json.dumps(payload, ensure_ascii=False))
