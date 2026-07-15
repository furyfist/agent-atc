"""Unit tests for the scenario runner's pass/fail logic and auto-approver
decision policy - the parts with real behavior beyond thin orchestration
(run_mission itself is covered by test_mission.py; AutoApprover talks to a
real gateway over HTTP so it's exercised live via the CLI, not mocked here).
"""

from __future__ import annotations

import httpx
import pytest

from agent_runner.mission import MissionLog, ToolCallRecord
from agent_runner.scenario_runner import AutoApprover, ScenarioResult


def _log(*calls: tuple[str, str], error: str | None = None) -> MissionLog:
    log = MissionLog(agent_id="coder-01")
    log.error = error
    for tool, result_text in calls:
        log.tool_calls.append(ToolCallRecord(tool=tool, arguments={}, result_text=result_text))
    return log


# --- ScenarioResult.passed ----------------------------------------------------


def test_passes_when_enumerate_then_deny_then_recover() -> None:
    log = _log(
        ("db__query", "3 rows"),
        ("db__execute", "[ATC-DENIED] reason=denied_by_human ..."),
        ("db__execute", "execute ran: ok"),
    )
    result = ScenarioResult(log=log, denials_seen=1, approvals_seen=1)
    assert result.passed is True


def test_fails_when_first_call_is_itself_denied() -> None:
    """Agent guessed a destructive action first instead of inspecting -
    S4's v1-prompt failure mode."""
    log = _log(("db__execute", "[ATC-DENIED] reason=..."))
    result = ScenarioResult(log=log, denials_seen=1, approvals_seen=0)
    assert result.passed is False


def test_fails_when_never_denied() -> None:
    """No HIGH-risk hold ever happened - not the Act 2 shape at all."""
    log = _log(("db__query", "3 rows"), ("db__execute", "execute ran: ok"))
    result = ScenarioResult(log=log, denials_seen=0, approvals_seen=0)
    assert result.passed is False


def test_fails_when_denied_but_never_recovers() -> None:
    """Denied and then... nothing else happens (agent gave up or ran out
    of turns) - denial without recovery isn't a pass."""
    log = _log(("db__query", "3 rows"), ("db__execute", "[ATC-DENIED] reason=..."))
    result = ScenarioResult(log=log, denials_seen=1, approvals_seen=0)
    assert result.passed is False


def test_fails_when_denied_twice_with_no_successful_recovery_between() -> None:
    """Same failure mode gap #4 in REMAINING_WORK.md flagged: repeated
    denied retries never actually succeed."""
    log = _log(
        ("db__query", "3 rows"),
        ("db__execute", "[ATC-DENIED] reason=..."),
        ("db__execute", "[ATC-DENIED] reason=..."),
        ("db__execute", "[ATC-DENIED] reason=..."),
    )
    result = ScenarioResult(log=log, denials_seen=3, approvals_seen=0)
    assert result.passed is False


def test_fails_on_mission_error() -> None:
    log = _log(
        ("db__query", "3 rows"),
        ("db__execute", "[ATC-DENIED] reason=..."),
        ("db__execute", "execute ran: ok"),
        error="ConnectionError: boom",
    )
    result = ScenarioResult(log=log, denials_seen=1, approvals_seen=1)
    assert result.passed is False


# --- AutoApprover --------------------------------------------------------------


async def test_auto_approver_denies_first_hold_then_approves_next() -> None:
    decisions: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            # Two pending holds across two poll cycles, same agent both times.
            call_n = handler.calls
            handler.calls += 1
            if call_n == 0:
                return httpx.Response(
                    200, json=[{"agent_id": "coder-01", "action_id": "a1"}]
                )
            return httpx.Response(200, json=[{"agent_id": "coder-01", "action_id": "a2"}])
        # POST /api/actions/{id}/{approve|deny}
        endpoint = request.url.path.rsplit("/", 1)[-1]
        action_id = request.url.path.split("/")[-2]
        decisions.append((action_id, endpoint))
        return httpx.Response(200, json={})

    handler.calls = 0
    transport = httpx.MockTransport(handler)

    async with httpx.AsyncClient(base_url="http://gateway.test", transport=transport) as client:
        approver = AutoApprover(client)
        await approver._decide({"agent_id": "coder-01", "action_id": "a1"})
        await approver._decide({"agent_id": "coder-01", "action_id": "a2"})

    assert decisions == [("a1", "deny"), ("a2", "approve")]
    assert approver.denials == 1
    assert approver.approvals == 1


async def test_auto_approver_denies_first_hold_per_agent_independently() -> None:
    decisions: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        endpoint = request.url.path.rsplit("/", 1)[-1]
        action_id = request.url.path.split("/")[-2]
        decisions.append((action_id, endpoint))
        return httpx.Response(200, json={})

    transport = httpx.MockTransport(handler)

    async with httpx.AsyncClient(base_url="http://gateway.test", transport=transport) as client:
        approver = AutoApprover(client)
        await approver._decide({"agent_id": "coder-01", "action_id": "a1"})
        await approver._decide({"agent_id": "assist-01", "action_id": "b1"})

    # Each agent gets its own "first hold" denied independently.
    assert decisions == [("a1", "deny"), ("b1", "deny")]
    assert approver.denials == 2
