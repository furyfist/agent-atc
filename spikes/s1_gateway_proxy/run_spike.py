"""Spike S1 harness: launches upstream, gateway, and agent as three separate
OS processes, then checks the combined logs for the three things S1 must
prove (PROJECT_PLAN.md S12):

  1. dynamic tools/list aggregation (db__query, db__execute both discovered)
  2. one traceparent-derived trace_id shared across all three process logs
  3. the held call actually ran the full ~120s before auto-denying

Exit code 0 = pass, 1 = fail. Prints a PASS/FAIL summary either way.
"""

from __future__ import annotations

import re
import subprocess
import sys
import time
from pathlib import Path

SPIKE_DIR = Path(__file__).parent
LOG_DIR = SPIKE_DIR / "logs"
TRACE_ID_RE = re.compile(r"trace_id=([0-9a-f]{32})")


def _start(script: str, log_path: Path) -> subprocess.Popen:
    log_file = log_path.open("w", encoding="utf-8")
    return subprocess.Popen(
        [sys.executable, script],
        cwd=SPIKE_DIR,
        stdout=log_file,
        stderr=subprocess.STDOUT,
    )


def main() -> int:
    LOG_DIR.mkdir(exist_ok=True)
    upstream_log = LOG_DIR / "upstream.log"
    gateway_log = LOG_DIR / "gateway.log"
    agent_log = LOG_DIR / "agent.log"

    print("[harness] starting upstream_server.py ...")
    upstream_proc = _start("upstream_server.py", upstream_log)
    time.sleep(1.5)  # give it a head start before the gateway tries to connect

    print("[harness] starting gateway.py ...")
    gateway_proc = _start("gateway.py", gateway_log)
    time.sleep(1.5)

    print("[harness] starting agent.py (this call blocks for ~120s on the held tool call) ...")
    agent_start = time.monotonic()
    try:
        agent_result = subprocess.run(
            [sys.executable, "agent.py"],
            cwd=SPIKE_DIR,
            capture_output=True,
            text=True,
            timeout=170,
        )
        agent_log.write_text(agent_result.stdout + agent_result.stderr, encoding="utf-8")
        agent_ok = agent_result.returncode == 0
    except subprocess.TimeoutExpired as exc:
        agent_log.write_text((exc.stdout or "") + (exc.stderr or ""), encoding="utf-8")
        agent_ok = False
    agent_wall_time = time.monotonic() - agent_start

    print("[harness] stopping upstream and gateway ...")
    for proc in (gateway_proc, upstream_proc):
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()

    upstream_text = upstream_log.read_text(encoding="utf-8")
    gateway_text = gateway_log.read_text(encoding="utf-8")
    agent_text = agent_log.read_text(encoding="utf-8")

    checks: list[tuple[str, bool]] = []

    checks.append(("agent process exited 0", agent_ok))

    trace_ids = {
        "agent": set(TRACE_ID_RE.findall(agent_text)),
        "gateway": set(TRACE_ID_RE.findall(gateway_text)),
        "upstream": set(TRACE_ID_RE.findall(upstream_text)),
    }
    shared_trace_id = trace_ids["agent"] & trace_ids["gateway"] & trace_ids["upstream"]
    checks.append((
        f"traceparent propagated across all 3 processes (shared trace_id: {shared_trace_id or 'NONE'})",
        bool(shared_trace_id),
    ))

    checks.append((
        "dynamic tools/list aggregation (db__query + db__execute)",
        "'db__query'" in agent_text and "'db__execute'" in agent_text,
    ))

    hold_match = re.search(r"HOLD_RESOLVED .*elapsed=([\d.]+)s", gateway_text)
    hold_elapsed = float(hold_match.group(1)) if hold_match else -1.0
    checks.append((
        f"held call survived the full ~120s hold in the gateway (elapsed={hold_elapsed}s)",
        115 <= hold_elapsed <= 135,
    ))

    checks.append(("auto-deny fired with the correct denial shape", "[ATC-DENIED]" in agent_text))
    checks.append((f"agent wall-clock time consistent with a real 120s hold ({agent_wall_time:.1f}s)", agent_wall_time >= 115))

    print("\n=== S1 SPIKE RESULTS ===")
    all_pass = True
    for description, ok in checks:
        status = "PASS" if ok else "FAIL"
        if not ok:
            all_pass = False
        print(f"[{status}] {description}")

    print(f"\nLogs: {LOG_DIR}")
    print("SPIKE S1: " + ("PASS" if all_pass else "FAIL"))
    return 0 if all_pass else 1


if __name__ == "__main__":
    raise SystemExit(main())
