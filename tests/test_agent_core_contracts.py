from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import sys


_CONTRACTS_PATH = Path(__file__).resolve().parents[1] / "agent" / "core" / "contracts.py"
_SPEC = spec_from_file_location("test_agent_core_contracts_module", _CONTRACTS_PATH)
contracts = module_from_spec(_SPEC)
assert _SPEC is not None and _SPEC.loader is not None
sys.modules[_SPEC.name] = contracts
_SPEC.loader.exec_module(contracts)

DelegationRequest = contracts.DelegationRequest
P2PMessage = contracts.P2PMessage
is_delegation_request = contracts.is_delegation_request


def test_p2pmessage_sender_and_receiver_properties_expose_aliases():
    message = P2PMessage(
        task_id="task-1",
        reply_to="supervisor",
        target_agent="reviewer",
        payload="review this change",
    )

    assert message.sender == "supervisor"
    assert message.receiver == "reviewer"


def test_is_delegation_request_accepts_direct_instance():
    request = DelegationRequest(
        task_id="task-2",
        reply_to="coder",
        target_agent="reviewer",
        payload="please review",
    )

    assert is_delegation_request(request) is True
