"""CoverageAgent missing-test generation and write helpers."""

from __future__ import annotations

import contextlib
import hashlib
import json
import shlex
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from agent.roles.coverage_agent import CoverageAgent


async def generate_test_candidate(
    agent: CoverageAgent, *, target_path: str, pytest_output: str, analysis: dict[str, Any]
) -> str:
    read_ok, source_excerpt = (
        await agent._call_maybe_async(agent.code.read_file, target_path)
        if target_path
        else (False, "")
    )
    prompt = (
        f"Hedef modül: {target_path or 'belirlenemedi'}\n"
        f"Önerilen test yolu: {agent._suggest_test_path(target_path)}\n"
        f"Pytest özeti: {analysis.get('summary', '')}\n"
        f"Bulgular: {json.dumps(analysis.get('findings', []), ensure_ascii=False)}\n\n"
        f"[PYTEST OUTPUT]\n{pytest_output[:4000]}\n\n"
        f"[KAYNAK DOSYA]\n{source_excerpt[:4000] if read_ok else 'kaynak okunamadı'}"
    )
    return await agent.call_llm(
        [{"role": "user", "content": prompt}],
        system_prompt=agent.TEST_GENERATION_PROMPT,
        temperature=0.1,
    )


async def tool_generate_missing_tests(agent: CoverageAgent, arg: str) -> str:
    payload = agent._parse_payload(arg)
    target_path = str(payload.get("target_path", "") or "")
    pytest_output = str(payload.get("pytest_output", "") or "")
    analysis = payload.get("analysis")
    coverage_finding = (
        payload.get("coverage_finding")
        if isinstance(payload.get("coverage_finding"), dict)
        else None
    )
    coveragerc_raw = payload.get("coveragerc")
    coveragerc: dict[str, Any] = coveragerc_raw if isinstance(coveragerc_raw, dict) else {}
    if coverage_finding and not target_path:
        target_path = str(coverage_finding.get("target_path", "") or "")
    if coverage_finding:
        source_excerpt = ""
        if target_path:
            read_ok, source_text = await agent._call_maybe_async(agent.code.read_file, target_path)
            if read_ok:
                source_excerpt = str(source_text or "")
        payload_prompt = agent._build_dynamic_pytest_prompt(
            finding=coverage_finding,
            coveragerc=coveragerc,
            source_excerpt=source_excerpt,
        )
        llm_candidate_or_idea = await agent.call_llm(
            [{"role": "user", "content": payload_prompt}],
            system_prompt=agent.TEST_GENERATION_PROMPT,
            temperature=0.1,
        )
        cleaned_candidate = agent._clean_code_output(str(llm_candidate_or_idea or ""))
        if agent._candidate_rejection_reason(cleaned_candidate, finding=coverage_finding):
            return agent._build_deterministic_test_template(
                finding=coverage_finding,
                llm_idea=str(llm_candidate_or_idea or ""),
            )
        return cleaned_candidate
    if not isinstance(analysis, dict):
        analysis = await agent._call_maybe_async(agent.code.analyze_pytest_output, pytest_output)
    return await agent._generate_test_candidate(
        target_path=target_path, pytest_output=pytest_output, analysis=analysis
    )


async def tool_write_missing_tests(agent: CoverageAgent, arg: str) -> str:
    payload = agent._parse_payload(arg)
    suggested_test_path = str(payload.get("suggested_test_path", "") or "")
    generated_test = agent._clean_code_output(str(payload.get("generated_test", "") or ""))
    append = bool(payload.get("append", True))
    validation_ok, validation_message, validation_details = (
        agent._validate_generated_test_before_write(
            suggested_test_path=suggested_test_path,
            generated_test=generated_test,
            append=append,
        )
    )
    if not validation_ok:
        return json.dumps(
            {
                "success": False,
                "suggested_test_path": suggested_test_path,
                "message": validation_message,
                "validation": validation_details,
            },
            ensure_ascii=False,
        )

    ok, message = await agent._call_maybe_async(
        agent.code.write_generated_test,
        suggested_test_path,
        generated_test,
        append=append,
    )
    return json.dumps(
        {
            "success": ok,
            "suggested_test_path": suggested_test_path,
            "message": message,
            "validation": {"message": validation_message, **validation_details},
        },
        ensure_ascii=False,
    )


async def validate_candidate_with_isolated_pytest(
    agent: CoverageAgent, *, suggested_test_path: str, generated_test: str
) -> tuple[bool, str, dict[str, Any]]:
    """Validate a candidate test in a temporary file with `uv run pytest <test_file>`."""
    base_dir = Path(agent.cfg.BASE_DIR)
    validation_dir = base_dir / "artifacts" / "coverage_candidate_validation"
    digest = hashlib.sha256(generated_test.encode("utf-8", errors="ignore")).hexdigest()[:12]
    stem = Path(suggested_test_path or "generated_candidate.py").stem or "generated_candidate"
    candidate_path = validation_dir / f"{stem}_{digest}.py"
    details: dict[str, Any] = {
        "isolated_test_file": str(candidate_path),
        "isolated_pytest_command": "",
    }
    try:
        validation_dir.mkdir(parents=True, exist_ok=True)
        candidate_path.write_text(generated_test, encoding="utf-8")
        try:
            command_path = candidate_path.relative_to(base_dir)
        except ValueError:
            command_path = candidate_path
        command = f"uv run pytest -q {shlex.quote(str(command_path))}"
        details["isolated_pytest_command"] = command
        result = await agent._call_maybe_async(
            agent.code.run_pytest_and_collect,
            command,
            str(base_dir),
        )
    except Exception as exc:  # noqa: BLE001 - validation must fail closed.
        details["error"] = str(exc)
        return False, "generated_candidate_isolated_pytest_error", details
    finally:
        with contextlib.suppress(OSError):
            candidate_path.unlink()

    if not isinstance(result, dict):
        details["result_type"] = type(result).__name__
        return False, "generated_candidate_isolated_pytest_invalid_result", details
    analysis = result.get("analysis") if isinstance(result.get("analysis"), dict) else {}
    has_failures = bool(analysis.get("has_failures", False)) if isinstance(analysis, dict) else False
    success = bool(result.get("success", not has_failures))
    details["result"] = {
        "success": success,
        "command": str(result.get("command", "") or ""),
        "output_excerpt": str(result.get("output", "") or "")[:1000],
    }
    if not success or has_failures:
        return False, "generated_candidate_isolated_pytest_failed", details
    return True, "isolated_pytest_passed", details
