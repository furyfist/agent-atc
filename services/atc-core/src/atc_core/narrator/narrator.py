"""The Narrator: fetches a trace's timeline, condenses it, asks Groq for a
plain-English causal explanation, and caches the result. See
PROJECT_PLAN.md S8.

`chat_fn` is injected (system_prompt, user_content) -> narrative text -
same pattern as agent_runner.mission's injectable chat_fn, for the same
reason: testable without spending real Groq budget or hard-wiring the SDK.
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable

from atc_core.narrator.condense import condense_timeline
from atc_core.narrator.span_fetcher import SpanFetcher
from atc_core.store import Store

NarratorChatFn = Callable[[str, str], Awaitable[str]]

SYSTEM_PROMPT = """You are the ATC Narrator. Given a condensed timeline of
governance events for one agent mission, explain in 3-5 sentences, in plain
English, what the agent did and why - especially any point where a human had
to intervene (an [ATC-DENIED] or approval). Be factual and concise. Do not
invent details that are not present in the timeline."""

NO_ACTIVITY_TEXT = "No recorded activity found for this trace."


class Narrator:
    def __init__(self, *, store: Store, span_fetcher: SpanFetcher, chat_fn: NarratorChatFn) -> None:
        self._store = store
        self._span_fetcher = span_fetcher
        self._chat_fn = chat_fn

    async def narrate(self, trace_id: str) -> str:
        cached = await self._store.get_narration(trace_id)
        if cached is not None:
            return cached

        spans = await self._span_fetcher.fetch_spans(trace_id)
        if not spans:
            await self._store.upsert_narration(trace_id, NO_ACTIVITY_TEXT, time.time())
            return NO_ACTIVITY_TEXT

        timeline = condense_timeline(spans)
        text = await self._chat_fn(SYSTEM_PROMPT, timeline)
        await self._store.upsert_narration(trace_id, text, time.time())
        return text
