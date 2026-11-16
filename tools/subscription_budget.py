"""API-equivalent accounting for the existing OpenCode subscription, not its quota meter."""

import argparse
from decimal import Decimal
import json
import subprocess
import shutil
import os

from .development import ROOT, now, write_json
from .errors import CoreError
from .safeio import SafeRoot

SESSION = "ses_e2af25196ffek6KaSgw0npVWAM"
RATES = {"input": 4, "output": 15, "cache_read": 0.2, "cache_write": 10}


def host_executable():
    with SafeRoot(ROOT) as root:
        configured = root.exists(".local") and root.exists(".local/opencode-runtime.json")
    if configured:
        from .diagnostics import opencode_runtime

        return opencode_runtime(ROOT)["executable"]
    found = shutil.which("opencode")
    if not found:
        raise CoreError("BUDGET_UNAVAILABLE", "OpenCode executable unavailable", 3)
    return found  # Legacy local ledger; no imported runtime profile is accepted.


def read_session(session_id):
    if (
        not isinstance(session_id, str)
        or not session_id.startswith("ses_")
        or not session_id.replace("_", "").isalnum()
    ):
        raise CoreError("BUDGET_SESSION", "Invalid host session identity")
    result = subprocess.run(
        [host_executable(), "api", "get", "/api/session/" + session_id], capture_output=True, timeout=30
    )
    if result.returncode:
        raise CoreError("BUDGET_UNAVAILABLE", "Cannot read local host token accounting; no new model dispatch", 3)
    data = json.loads(result.stdout)
    data = data.get("data", data)
    return {key: data[key] for key in ("id", "model", "cost", "tokens") if key in data}


def upper_cost(tokens):
    def counter(value):
        return type(value) in (int, float) and Decimal(str(value)).is_finite() and value >= 0

    if (
        not isinstance(tokens, dict)
        or any(not counter(tokens.get(k)) for k in ("input", "output", "reasoning"))
        or not isinstance(tokens.get("cache"), dict)
        or any(not counter(tokens["cache"].get(k)) for k in ("read", "write"))
    ):
        raise CoreError("BUDGET_USAGE_UNKNOWN", "Missing usage counters; retain reservations and reconcile", 3)
    # Count reasoning in addition to output conservatively: some runtimes include
    # it in output, some separate it. Never subtract an unverified cache discount.
    n = Decimal(str(tokens["input"])) * Decimal(str(RATES["input"]))
    n += (Decimal(str(tokens["output"])) + Decimal(str(tokens["reasoning"]))) * Decimal(str(RATES["output"]))
    n += Decimal(str(tokens["cache"]["read"])) * Decimal(str(RATES["cache_read"]))
    n += Decimal(str(tokens["cache"]["write"])) * Decimal(str(RATES["cache_write"]))
    cost = float(n / Decimal(1000000))
    if not Decimal(str(cost)).is_finite():
        raise CoreError("BUDGET_USAGE_UNKNOWN", "Usage cost is not finite; retain reservations and reconcile", 3)
    return cost


def snapshot(reserve=0, reservation=None):
    with SafeRoot(ROOT) as root:
        with root.lock(".local/subscription-budget.lock"):
            path = ".local/subscription-budget.json"
            state = root.json(path)
            info = os.fstat(root.fd)
            if state.get("local_root") not in (None, {"device": info.st_dev, "inode": info.st_ino}):
                raise CoreError("BUDGET_IMPORTED", "Budget belongs to another installation", 3)
            leader = read_session(state["leader_session"])
            if leader["model"]["providerID"] != "codex" or leader["model"]["id"] != "gpt-6.1-sol":
                raise CoreError("BUDGET_MODEL", "Current model differs from priced authorized profile", 3)
            current = upper_cost(leader["tokens"])
            spent = max(0, current - state["baseline_upper_USD"])
            spent += sum(row["upper_USD"] for row in state["other_sessions"])
            outstanding = sum(
                row["USD"] for row in state["reservations"] if row["status"] in {"reserved", "outcome_unknown"}
            )
            available = state["limit_USD"] - spent - outstanding
            state.update(
                updated_at=now(),
                measured_additional_API_equivalent_upper_USD=spent,
                current_leader_metadata=leader,
                available_API_equivalent_USD=available,
                pending_requested_reservation_USD=reserve,
            )
            if reserve > available:
                raise CoreError("BUDGET_LIMIT", "Additional model call would exceed API-equivalent cap", 3)
            if reservation is not None:
                if reservation["USD"] != reserve or reserve <= 0:
                    raise CoreError("BUDGET_RESERVATION", "Reservation must match the checked positive amount")
                identity = reservation.get("external_identity")
                grant_identity = reservation.get("grant_identity")
                if grant_identity and any(row.get("grant_identity") == grant_identity for row in state["reservations"]):
                    raise CoreError(
                        "GRANT_ALREADY_USED",
                        "This one-use human grant is already reserved, unknown or completed; never repeat it in another run",
                        3,
                    )
                if identity and any(row.get("external_identity") == identity for row in state["reservations"]):
                    raise CoreError(
                        "HOST_RECONCILE_REQUIRED",
                        "This actual model request already has a pending, unknown or completed reservation; do not repeat it",
                        3,
                    )
                if any(row["id"] == reservation["id"] for row in state["reservations"]):
                    raise CoreError("BUDGET_RESERVATION", "Reservation identity already exists", 3)
                state["reservations"].append(reservation)
                state["available_API_equivalent_USD"] -= reserve
            root.write(path, (json.dumps(state, ensure_ascii=False, indent=2) + "\n").encode())
            return state


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reserve-check", type=float, default=0)
    args = parser.parse_args()
    state = snapshot(args.reserve_check)
    print(
        json.dumps(
            {
                key: state[key]
                for key in (
                    "limit_USD",
                    "measured_additional_API_equivalent_upper_USD",
                    "available_API_equivalent_USD",
                    "subscription_quota_remaining",
                    "limitations",
                )
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
