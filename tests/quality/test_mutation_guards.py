from __future__ import annotations

import pytest

from agent.core.contracts import DelegationRequest
from agent.core.supervisor import SupervisorAgent


def _assert_validate_p2p_contract() -> None:
    assert (
        SupervisorAgent._validate_p2p_request(
            DelegationRequest(task_id="t", reply_to="r", target_agent="c", payload="x")
        )
        is None
    )
    assert "reply_to" in str(
        SupervisorAgent._validate_p2p_request(
            DelegationRequest(task_id="t", reply_to="", target_agent="c", payload="x")
        )
    )
    assert "target_agent" in str(
        SupervisorAgent._validate_p2p_request(
            DelegationRequest(task_id="t", reply_to="r", target_agent="", payload="x")
        )
    )
    assert "payload" in str(
        SupervisorAgent._validate_p2p_request(
            DelegationRequest(task_id="t", reply_to="r", target_agent="c", payload="")
        )
    )


def _assert_reject_feedback_contract() -> None:
    assert SupervisorAgent._is_reject_feedback_payload('qa_feedback|{"decision":"reject"}') is True
    assert (
        SupervisorAgent._is_reject_feedback_payload('qa_feedback|{"decision":"approve"}') is False
    )
    assert SupervisorAgent._is_reject_feedback_payload("plain-text") is False


def test_mutation_guard_kills_validate_p2p_inverted_missing_check(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _mutant_validate(request: DelegationRequest):
        # Mutant: eksik alanları raporlamak yerine yanlışlıkla ters koşul kullanır.
        missing_fields: list[str] = []
        if str(getattr(request, "reply_to", "") or "").strip():
            missing_fields.append("reply_to")
        if str(getattr(request, "target_agent", "") or "").strip():
            missing_fields.append("target_agent")
        if str(getattr(request, "payload", "") or "").strip():
            missing_fields.append("payload")
        return ", ".join(missing_fields) if missing_fields else None

    monkeypatch.setattr(SupervisorAgent, "_validate_p2p_request", staticmethod(_mutant_validate))

    with pytest.raises(AssertionError):
        _assert_validate_p2p_contract()


def test_mutation_guard_kills_reject_feedback_decision_flip(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _mutant_is_reject(payload: object) -> bool:
        text = str(payload or "")
        if not text.startswith("qa_feedback|"):
            return False
        body = text.split("|", 1)[1].strip()
        # Mutant: reject/approve anlamını yanlışlıkla tersine çevirir.
        return "decision=reject" not in body.lower()

    monkeypatch.setattr(
        SupervisorAgent, "_is_reject_feedback_payload", staticmethod(_mutant_is_reject)
    )

    with pytest.raises(AssertionError):
        _assert_reject_feedback_contract()
