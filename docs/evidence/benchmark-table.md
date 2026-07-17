# Benchmark/summary table (§6 item 8)

Pulled 2026-07-17 ~20:20 UTC via `scripts/action_summary.py` against the
live `atc.sqlite3` `actions` table, after experiments #1-#8 and #10 ran
(experiment #9 blocked mid-run by the daily Groq cap - see
`exp09-concurrent-queue.md` - so its numbers aren't reflected here beyond
the single `coder-01` query it got in before the 429).

## Counts by risk level x decision

| Risk   | Decision     | Count |
|--------|--------------|-------|
| HIGH   | APPROVED     | 1     |
| HIGH   | DENIED       | 3     |
| HIGH   | EXPIRED      | 16    |
| LOW    | AUTO_ALLOWED | 75    |
| MEDIUM | AUTO_ALLOWED | 22    |

117 actions total.

## Denial rate by rule_id

| Rule                              | Denied/Total | Rate   |
|------------------------------------|-------------|--------|
| FS-READ-LOW                        | 0/46        | 0.0%   |
| SQL-READ-LOW                       | 0/29        | 0.0%   |
| FS-WRITE-MEDIUM                    | 0/20        | 0.0%   |
| SQL-DESTRUCTIVE-DDL-HIGH           | 1/16        | 6.2%   |
| SQL-PROD-TABLE-HIGH                | 1/2         | 50.0%  |
| UNMATCHED-FAIL-CLOSED              | 0/1         | 0.0%   |
| SQL-WRITE-MEDIUM                   | 0/1         | 0.0%   |
| SQL-UNRECOGNIZED-STATEMENT-HIGH    | 1/1         | 100.0% |
| SQL-UNBOUNDED-WRITE-HIGH           | 0/1         | 0.0%   |

(SQL-PROD-TABLE-HIGH and SQL-UNRECOGNIZED-STATEMENT-HIGH's small
denominators are experiments #1 and #10 respectively - single, deliberate
live-watched runs, not statistical samples.)

## Approval latency percentiles (human-decided HELD actions, n=4)

| Percentile | Latency  |
|------------|----------|
| p50        | 19.254s  |
| p95        | 92.998s  |
| p99        | 100.825s |

Small n (4) - this is every human-decided HIGH-risk action across today's
experiments, not a statistically robust sample. The spread (19s to 101s)
reflects genuinely different decision contexts: some denials came within
seconds of a live-watched pending card (experiment #1's first decision),
others waited closer to the 120s hold timeout because nobody was
watching (the naturally-recurring `coder-01` persona's unattended DROP
attempts before this session's live experiments began).

## Governance friction rate

**20/117 (17.1%)** of all actions were held for approval (PENDING,
APPROVED, DENIED, or EXPIRED) rather than auto-allowed.

## Honesty note

This table mixes several different experiment shapes (live-watched
single decisions, a fully unattended natural persona loop, and one
red-team probe) rather than one controlled run - it is a real,
un-invented snapshot of everything that happened during this evidence-
gathering session, exactly as it happened, not a designed statistical
sample. Re-run `scripts/action_summary.py` after any further experiments
(especially #9, once quota resets) to get an updated table before
finalizing the blog.
