# Experiment #12 — Journal pre-image capture, honestly framed

Pulled 2026-07-18, directly from `atc.sqlite3`'s `journal` table, for the
same action as `exp07-blast-radius.md`'s bounded UPDATE — no separate
trigger needed, since journal capture runs automatically, post-approval
pre-execution, for every COMPENSABLE mutation (`gateway/journal.py`).

## What actually happened

```sql
UPDATE orders SET total = total * 1.1 WHERE id >= 1000
```

Before this ran, the gateway issued the equivalent `SELECT * FROM orders
WHERE id >= 1000` through the same upstream connection pool the mutation
itself would use, and stored the result as the pre-image:

```json
{
  "action_id": "136cd135-d5b0-4217-b746-57a10ca3a680",
  "kind": "db_rows",
  "created_at": 1784394017.0258713,
  "undone_at": null,
  "undo_action_id": null
}
```

Payload (`table: orders`, 200 rows captured, exact prior values before
the 1.1x update):

```json
{"table": "orders", "rows": [
  {"id": 1000, "customer_id": 1, "total": 10.0},
  {"id": 1001, "customer_id": 2, "total": 11.0},
  {"id": 1002, "customer_id": 1, "total": 12.0},
  ...197 more rows...
]}
```

This is a real, exact recovery snapshot — if a compensating write existed,
it could restore `orders.total` to precisely these values, row by row.

## Correction (2026-07-19): the undo executor is real

This section originally said no undo executor existed. That was accurate
when this file was first written, but wrong by the time it was published.
Commit `3ab1433` ("synthesize compensating tool calls from journaled
pre-images") landed the same evening, shortly after the journal itself,
and this file was never rechecked against it.

What's actually there: `POST /api/actions/{action_id}/undo`
(`services/atc-core/src/atc_core/api/routes.py:124-190`) reads the
journal entry for an action, builds real compensating tool calls via
`gateway/undo.py`'s `build_compensation()` (`fs__write`/`fs__delete` for
file journal entries, `INSERT OR REPLACE` statements for db row/table
entries), and executes them through the same governed upstream pool
every other tool call uses. The undo itself is recorded as a new linked
action row (`rule_id=UNDO-COMPENSATION`, same `trace_id` as the original
mistake), so the recovery is exactly as auditable as the thing it's
undoing. `Store.mark_undone()`'s compare-and-swap
(`UPDATE journal SET undone_at=?, undo_action_id=? WHERE action_id=? AND
undone_at IS NULL`) guards against two concurrent undo clicks both
"winning." 31/31 tests pass across `test_undo_builder.py` and
`test_api.py`.

What's still true: nobody has actually called it on a real journaled
action from this evidence-gathering session. Confirmed directly against
the live database:

```sql
SELECT count(*) FROM journal WHERE undone_at IS NOT NULL
-- 0
```

Every one of the 45+ journal rows accumulated during experiments is
still, as of this writing, capture-only in practice, not because the
undo path doesn't exist, but because we never exercised it live. That's
a real gap in the evidence, distinct from the gap this section originally
(and incorrectly) claimed.

## Why this correction belongs in the blog, not a quiet fix

The whole point of this evidence log is that every claim is checked
against the live system before it goes in the post. This one wasn't
rechecked after the code changed underneath it, and it would have shipped
wrong. Leaving the mistake visible, corrected in place, is more honest
than silently rewriting history to look like we got it right the first
time.
