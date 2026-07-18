#!/usr/bin/env python3
"""Print action counts by risk_level x decision, plus approval-latency
percentiles and denial rate by rule, from the ATC SQLite store.

Usage: python scripts/action_summary.py [path/to/atc.sqlite3]
Default path matches ATC_SQLITE_PATH's in-container default; run via
`docker exec atc-atc-core-1 python3 - < scripts/action_summary.py` or point
it at a copied-out .sqlite3 file.
"""

import sqlite3
import sys

DEFAULT_PATH = "/data/atc.sqlite3"


def percentile(values: list[float], p: float) -> float | None:
    if not values:
        return None
    values = sorted(values)
    k = (len(values) - 1) * p
    f, c = int(k), min(int(k) + 1, len(values) - 1)
    if f == c:
        return values[f]
    return values[f] + (values[c] - values[f]) * (k - f)


def main() -> None:
    path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_PATH
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row

    print(f"=== Action summary: {path} ===\n")

    print("-- Counts by risk_level x decision --")
    rows = conn.execute(
        """
        SELECT risk_level, status AS decision, COUNT(*) AS n
        FROM actions
        GROUP BY risk_level, status
        ORDER BY risk_level, status
        """
    ).fetchall()
    if not rows:
        print("(no actions recorded)")
    for r in rows:
        print(f"  {r['risk_level']:<8} {r['decision']:<10} {r['n']}")

    print("\n-- Denial rate by rule_id --")
    rows = conn.execute(
        """
        SELECT rule_id,
               COUNT(*) AS total,
               SUM(CASE WHEN status = 'DENIED' THEN 1 ELSE 0 END) AS denied
        FROM actions
        GROUP BY rule_id
        ORDER BY total DESC
        """
    ).fetchall()
    if not rows:
        print("(no actions recorded)")
    for r in rows:
        rate = (r["denied"] / r["total"] * 100) if r["total"] else 0.0
        print(f"  {r['rule_id']:<30} {r['denied']}/{r['total']} denied ({rate:.1f}%)")

    print("\n-- Approval latency percentiles (seconds, human-decided HELD actions) --")
    rows = conn.execute(
        """
        SELECT requested_at, resolved_at
        FROM actions
        WHERE status IN ('APPROVED', 'DENIED')
          AND resolved_at IS NOT NULL
        """
    ).fetchall()
    latencies = [r["resolved_at"] - r["requested_at"] for r in rows]
    if latencies:
        for p in (0.5, 0.95, 0.99):
            print(f"  p{int(p * 100)}: {percentile(latencies, p):.3f}s")
        print(f"  n = {len(latencies)}")
    else:
        print("(no resolved actions with latency data)")

    print("\n-- Governance friction rate (held-for-approval / total actions) --")
    total = conn.execute("SELECT COUNT(*) AS n FROM actions").fetchone()["n"]
    held = conn.execute(
        "SELECT COUNT(*) AS n FROM actions WHERE status IN ('PENDING', 'APPROVED', 'DENIED', 'EXPIRED')"
    ).fetchone()["n"]
    if total:
        print(f"  {held}/{total} ({held / total * 100:.1f}%)")
    else:
        print("(no actions recorded)")

    conn.close()


if __name__ == "__main__":
    main()
