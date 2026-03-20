import importlib.util
import sys
from pathlib import Path

import core.ci_remediation as ci_mod

from tests.test_sidar_agent_runtime import SA_MOD



def _load_contracts_module(module_name: str = "contracts_small_gap_test"):
    spec = importlib.util.spec_from_file_location(module_name, Path("agent/core/contracts.py"))
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


CONTRACTS = _load_contracts_module()



def test_is_p2p_message_accepts_direct_instance_branch():
    message = CONTRACTS.P2PMessage(
        task_id="task-1",
        reply_to="supervisor",
        target_agent="reviewer",
        payload="review this change",
    )

    assert CONTRACTS.is_p2p_message(message) is True



def test_build_root_cause_summary_uses_failure_summary_default_when_no_other_signal_exists():
    summary = ci_mod.build_root_cause_summary(
        {
            "failure_summary": "",
            "log_excerpt": "",
            "root_cause_hint": "",
        },
        "\n   \n",
    )

    assert summary == "CI başarısızlığı için ek teşhis gerekiyor."


def test_sidar_agent_default_correlation_id_helper_returns_first_non_empty_value():
    assert SA_MOD._default_derive_correlation_id(None, "   ", "corr-42", "corr-43") == "corr-42"