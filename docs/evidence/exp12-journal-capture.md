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

## The honest limitation

The `journal` table schema has `undone_at` and `undo_action_id` columns
and `Store.mark_undone()` exists (a compare-and-swap update — `UPDATE
journal SET undone_at=?, undo_action_id=? WHERE action_id=? AND
undone_at IS NULL` — so two concurrent undo attempts on the same
journaled action can't both "win"). But across the entire codebase,
**nothing calls `mark_undone` outside its own unit test.** There is no
REST endpoint, no UI button, no compensating-action executor. Confirmed
directly against the live database:

```sql
SELECT count(*) FROM journal WHERE undone_at IS NOT NULL
-- 0
```

Every one of the 45 journal rows accumulated during today's experiments
is capture-only. `docs/PRODUCT_STRATEGY.md`'s pillar 1 ("the ejection
seat" — pre-execution journaling → one-click compensating actions →
blast-radius preview) has its first and third pieces built and proven
live today (journal capture, exp07's blast-radius estimate). The middle
piece — the actual undo — is the seed of a V2 feature, not a working
recovery system yet.

## Why this belongs in the blog as-is, not hidden

This is exactly the kind of claim the SignOz blog guide asks for
evidence on, and exactly the kind of claim that's tempting to round up.
The honest version is more interesting than an inflated one: readers can
see the exact mechanism that recovery would be built on (a real pre-image
with real row-level fidelity, captured through the same governed path
every other tool call takes), stated plainly as unfinished rather than
implied as done.
