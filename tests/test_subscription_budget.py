"""Accounting validation without host calls or production ledger writes."""

import json

import pytest

from tools import subscription_budget as budget
from tools.errors import CoreError


@pytest.mark.parametrize("field", ["input", "output", "reasoning", "read", "write"])
@pytest.mark.parametrize("value", [None, True, False, float("nan"), float("inf"), -1, "12", [], {}])
def test_malformed_usage_preserves_ledger_and_unknown_reservation(tmp_path, monkeypatch, field, value):
    tokens = {"input": 1, "output": 2, "reasoning": 3, "cache": {"read": 4, "write": 5}}
    (tokens["cache"] if field in {"read", "write"} else tokens)[field] = value
    state = {
        "leader_session": "ses_fixture",
        "baseline_upper_USD": 7,
        "reservations": [{"id": "unknown", "USD": 12, "status": "outcome_unknown"}],
    }
    path = tmp_path / ".local/subscription-budget.json"
    path.parent.mkdir()
    raw = json.dumps(state).encode()
    path.write_bytes(raw)
    monkeypatch.setattr(budget, "ROOT", tmp_path)
    monkeypatch.setattr(
        budget,
        "read_session",
        lambda session: {
            "model": {"providerID": "codex", "id": "gpt-6.1-sol"},
            "tokens": tokens,
        },
    )
    with pytest.raises(CoreError) as error:
        budget.snapshot()
    assert error.value.code == "BUDGET_USAGE_UNKNOWN"
    assert path.read_bytes() == raw


def test_upper_cost_conservatively_counts_all_counters():
    assert budget.upper_cost(
        {"input": 100, "output": 10, "reasoning": 2, "cache": {"read": 5, "write": 3}}
    ) == pytest.approx(0.000611)


def test_host_adapter_uses_current_validated_executable(monkeypatch):
    from types import SimpleNamespace
    from tools.adapters import opencode_model

    monkeypatch.setattr(budget, "host_executable", lambda: "/temporary/mock/opencode")
    calls = []
    monkeypatch.setattr(
        opencode_model.subprocess,
        "run",
        lambda command, **kw: calls.append(command) or SimpleNamespace(returncode=0, stdout=b"{}"),
    )
    assert opencode_model.api("get", "/fixture")[0] == {}
    assert calls == [["/temporary/mock/opencode", "api", "get", "/fixture"]]
