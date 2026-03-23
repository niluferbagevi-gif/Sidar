import core.ci_remediation as ci_mod
from core.ci_remediation import build_self_heal_patch_prompt, normalize_self_heal_plan


def test_allowed_validation_command_rejects_empty_bad_split_and_empty_parts(monkeypatch):
    assert ci_mod._is_allowed_validation_command("") is False
    assert ci_mod._is_allowed_validation_command('"unterminated') is False

    monkeypatch.setattr(ci_mod.shlex, "split", lambda _text: [])
    assert ci_mod._is_allowed_validation_command("pytest -q tests/test_ci_remediation.py") is False


def test_self_heal_prompt_skips_snapshot_entries_missing_path_or_content():
    prompt = build_self_heal_patch_prompt(
        {"repo": "acme/sidar", "workflow_name": "CI"},
        "diag",
        {"scope_paths": ["app.py"], "validation_commands": ["pytest -q tests/test_app.py"]},
        [
            {"path": "", "content": "ignored"},
            {"path": "empty.py", "content": ""},
            {"path": "app.py", "content": "VALUE = 1\n"},
        ],
    )

    assert "[FILE] app.py" in prompt
    assert "ignored" not in prompt
    assert "empty.py" not in prompt


def test_normalize_self_heal_plan_handles_non_json_code_fence_and_text_without_braces():
    plan = normalize_self_heal_plan(
        "```yaml\nsummary: nope\n```",
        scope_paths=["app.py"],
        fallback_validation_commands=["python -m pytest"],
    )

    assert plan["operations"] == []
    assert plan["validation_commands"] == ["python -m pytest"]


def test_normalize_self_heal_plan_handles_code_fence_parse_failures_and_invalid_shapes():
    fenced_invalid = normalize_self_heal_plan(
        "```json\n{not valid json}\n```",
        scope_paths=["app.py"],
        fallback_validation_commands=["python -m pytest"],
    )
    assert fenced_invalid["operations"] == []
    assert fenced_invalid["validation_commands"] == ["python -m pytest"]

    non_mapping = normalize_self_heal_plan(
        ["unexpected", "payload"],
        scope_paths=["app.py"],
        fallback_validation_commands=[],
    )
    assert non_mapping["operations"] == []
    assert non_mapping["validation_commands"] == []

    mixed_operations = normalize_self_heal_plan(
        {
            "operations": [
                "not-a-dict",
                {"action": "patch", "path": "app.py", "target": "A", "replacement": "B"},
            ],
            "validation_commands": ["pytest -q tests/test_app.py"],
        },
        scope_paths=["app.py"],
        fallback_validation_commands=[],
    )
    assert mixed_operations["operations"] == [
        {"action": "patch", "path": "app.py", "target": "A", "replacement": "B"}
    ]


def test_build_root_cause_summary_falls_back_to_malformed_log_excerpt_signal():
    summary = ci_mod.build_root_cause_summary(
        {
            "failure_summary": "CI parser malformed output aldı",
            "log_excerpt": "@@ broken payload <<<\nnot-json: [}\nSyntaxError: unexpected EOF while parsing",
        },
        "Ön analiz tamamlandı ama ilk satır kök neden içermiyor.",
    )

    assert summary == "SyntaxError: unexpected EOF while parsing"
