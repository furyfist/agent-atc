"""Real Groq-backed NarratorChatFn. Same 429-backoff shape as agent-runner's
groq_client.py (a separate, independently-deployable service - the small
duplication is cheaper than a shared dependency between them). Not wired
into a live entrypoint yet - atc-core doesn't have a real main.py/Docker
entrypoint yet either; that lands with the docker-compose milestone, which
is when something actually needs to construct this for real.
"""

from __future__ import annotations

import asyncio

from groq import APIStatusError, AsyncGroq

MODEL = "llama-3.3-70b-versatile"


def make_groq_chat_fn(client: AsyncGroq):
    async def chat_fn(system_prompt: str, user_content: str, *, max_retries: int = 5) -> str:
        delay = 2.0
        for attempt in range(max_retries):
            try:
                resp = await client.chat.completions.create(
                    model=MODEL,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_content},
                    ],
                    temperature=0.3,
                    max_tokens=300,
                )
                return resp.choices[0].message.content or ""
            except APIStatusError as exc:
                if exc.status_code == 429 and attempt < max_retries - 1:
                    await asyncio.sleep(delay)
                    delay *= 2
                    continue
                raise
        raise RuntimeError("exhausted retries")

    return chat_fn
