"""Async Groq chat-completions wrapper with 429 backoff. Proven pattern from
spike S4 (spikes/s4_groq_budget/agent_spike.py), moved to AsyncGroq so 3
concurrent agent loops (S4's service topology) don't block each other on a
synchronous network call.
"""

from __future__ import annotations

import asyncio
from typing import Any

from groq import APIStatusError, AsyncGroq

MODEL = "llama-3.3-70b-versatile"

# Reliability rehearsal (S12 S4) found temperature=0.0 makes every mission an
# identical replay - not meaningfully "reliable", just deterministic. 0.4 is
# low-ish and steerable while still producing real run-to-run variance.
DEFAULT_TEMPERATURE = 0.4


async def chat_with_backoff(
    client: AsyncGroq,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
    *,
    temperature: float = DEFAULT_TEMPERATURE,
    max_retries: int = 5,
) -> Any:
    delay = 2.0
    for attempt in range(max_retries):
        try:
            return await client.chat.completions.create(
                model=MODEL,
                messages=messages,
                tools=tools,
                temperature=temperature,
                max_tokens=512,
            )
        except APIStatusError as exc:
            if exc.status_code == 429 and attempt < max_retries - 1:
                await asyncio.sleep(delay)
                delay *= 2
                continue
            raise
    raise RuntimeError("exhausted retries")
