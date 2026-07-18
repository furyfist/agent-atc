# Benchmark/summary table (§6 item 8)

Pulled 2026-07-18 ~17:10 UTC via `scripts/action_summary.py` against the
live `atc.sqlite3` `actions` table, after all 12 P0 experiments (#1-#12)
had run at least once, including experiment #9's third (synthetic)
attempt that finally produced a genuine 2-hold concurrent queue.

## Counts by risk level x decision

| Risk   | Decision     | Count |
|--------|--------------|-------|
| HIGH   | APPROVED     | 4     |
| HIGH   | DENIED       | 7     |
| HIGH   | EXPIRED      | 37    |
| LOW    | AUTO_ALLOWED | 155   |
| MEDIUM | AUTO_ALLOWED | 49    |

252 actions total.

## Denial rate by rule_id

| Rule                              | Denied/Total | Rate   |
|------------------------------------|-------------|--------|
| FS-READ-LOW                        | 0/95        | 0.0%   |
| SQL-READ-LOW                       | 0/60        | 0.0%   |
| FS-WRITE-MEDIUM                    | 0/45        | 0.0%   |
| SQL-DESTRUCTIVE-DDL-HIGH           | 1/34        | 2.9%   |
| SQL-PROD-TABLE-HIGH                | 2/5         | 40.0%  |
| SQL-UNBOUNDED-WRITE-HIGH           | 0/4         | 0.0%   |
| FS-SENSITIVE-PATH-HIGH             | 3/3         | 100.0% |
| GIT-PUSH-MEDIUM                    | 0/2         | 0.0%   |
| UNMATCHED-FAIL-CLOSED              | 0/1         | 0.0%   |
| SQL-WRITE-MEDIUM                   | 0/1         | 0.0%   |
| SQL-UNRECOGNIZED-STATEMENT-HIGH    | 1/1         | 100.0% |
| FS-DELETE-HIGH                     | 0/1         | 0.0%   |

(FS-SENSITIVE-PATH-HIGH's 100% denial rate is genuinely representative,
not a small-n artifact of one experiment - it fired across the prompt
injection probe (#3), and both concurrent-queue attempts (#9). Every
other single-digit-denominator row below is still a small, deliberate
sample, not a statistical one - most notably SQL-PROD-TABLE-HIGH, whose
5 calls span experiments #1, #7, and #9.)

## Approval latency percentiles (human-decided HELD actions, n=11)

| Percentile | Latency  |
|------------|----------|
| p50        | 0.955s   |
| p95        | 80.344s  |
| p99        | 98.294s  |

n grew from 4 to 11 across this session (experiments #7, #9's synthetic
variant, and #10's after-fix re-run each added live human decisions).
The p50 dropped sharply (19.25s -> 0.955s) because several of today's
newer decisions were made near-instantly via direct API calls
(experiments #7 and #9b's `LiveApprover`/manual denials), rather than
waiting on a human watching a UI countdown - still a real decision
latency, just a different distribution shape than a human reading a
pending card. Worth noting as-is in the blog rather than smoothing over:
"human decision latency" spans a wide range of real decision-making
contexts, from instant scripted approval to a full 120s unattended
timeout.

## Governance friction rate

**48/252 (19.0%)** of all actions were held for approval (PENDING,
APPROVED, DENIED, or EXPIRED) rather than auto-allowed - up from 17.1%
in the prior snapshot, reflecting the additional deliberate HIGH-risk
holds from experiments #7, #9, and #10's re-verification.

## New in this pass: blast-radius and reversibility evidence

Not part of the original counts table but pulled from the same database
for experiments #7, #11, #12:

- Real blast-radius estimates observed: `~200 rows affected` (exp #7's
  bounded UPDATE on `orders`), `~202 rows affected` (exp #9's DROP TABLE
  on the same, now-larger `orders` table - confirms the estimate reflects
  live accumulated state, not a fixture reset).
- Reversibility distribution across the three tiers, each with a distinct
  real example: REVERSIBLE (`db__query`, LOW, AUTO_ALLOWED), COMPENSABLE
  (`db__execute` UPDATE, HIGH, APPROVED, journal-captured), IRREVERSIBLE
  (`git__push`, MEDIUM, AUTO_ALLOWED - the clearest case that risk and
  reversibility are genuinely separate axes).
- Journal table: 45+ rows accumulated, 0 ever marked `undone_at` -
  capture-only, honestly confirmed against the live schema.

## Honesty note

This table mixes several different experiment shapes (live-watched single
decisions, unattended natural persona-loop activity, synthetic zero-Groq
probes, and one red-team probe with a same-day fix) rather than one
controlled run - it is a real, un-invented snapshot of everything that
happened across two evidence-gathering sessions (2026-07-17 and
2026-07-18), exactly as it happened. Experiment #9's Groq-driven variant
never completed (see `exp09-concurrent-queue.md` for why - the fleet's
own idle loop exhausts a day's free-tier budget in under two hours); its
synthetic variant did, and that's the number reflected in "governance
friction rate" and the blast-radius section above.
