"""Reversibility classification: can this action be taken back?

Sits alongside risk level as a second, orthogonal consequence signal (risk =
how bad could it be; reversibility = can we recover if it was). Deterministic,
derived from the same sqlglot facts the rules already use, and fail-closed:
anything unrecognized is IRREVERSIBLE, so a new tool can only *reduce* the
warning by being classified, never dodge it.

COMPENSABLE means ATC's gateway journal can capture a pre-image before
execution and later synthesize a compensating call (see gateway/journal.py) -
it does not promise a perfect inverse, only that recovery data exists.
"""

from __future__ import annotations

from enum import Enum

from atc_core.risk.sql_facts import SqlFacts


class Reversibility(str, Enum):
    REVERSIBLE = "REVERSIBLE"  # pure read - nothing to undo
    COMPENSABLE = "COMPENSABLE"  # pre-image journal can restore prior state
    IRREVERSIBLE = "IRREVERSIBLE"  # no compensation exists once executed


_READ_TOOLS = frozenset({"db__query", "fs__read"})
_COMPENSABLE_TOOLS = frozenset({"fs__write", "fs__delete"})
# email can't be un-sent; a (force-)push publishes history to a remote we
# don't journal; ALTER/TRUNCATE lose structure/rows in ways a row-level
# pre-image doesn't capture faithfully.
_IRREVERSIBLE_TOOLS = frozenset({"email__send", "git__push", "git__force_push"})

_COMPENSABLE_DML = frozenset({"INSERT", "UPDATE", "DELETE"})
_COMPENSABLE_DDL = frozenset({"DROP", "CREATE"})


def classify(tool: str, sql_facts: SqlFacts | None) -> Reversibility:
    if tool in _READ_TOOLS:
        return Reversibility.REVERSIBLE
    if tool in _COMPENSABLE_TOOLS:
        return Reversibility.COMPENSABLE
    if tool in _IRREVERSIBLE_TOOLS:
        return Reversibility.IRREVERSIBLE

    if tool == "db__execute":
        if sql_facts is None:
            return Reversibility.IRREVERSIBLE  # unparseable SQL - fail closed
        if sql_facts.dml_kind == "SELECT":
            return Reversibility.REVERSIBLE
        if sql_facts.ddl_kind is not None:
            return (
                Reversibility.COMPENSABLE
                if sql_facts.ddl_kind in _COMPENSABLE_DDL
                else Reversibility.IRREVERSIBLE
            )
        if sql_facts.dml_kind in _COMPENSABLE_DML:
            return Reversibility.COMPENSABLE
        return Reversibility.IRREVERSIBLE

    return Reversibility.IRREVERSIBLE  # unknown tool - fail closed
