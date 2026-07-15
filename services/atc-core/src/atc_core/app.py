"""Top-level app assembly: one process serving /mcp, /api, /ws, and the
static approval UI. See PROJECT_PLAN.md S4's atc-core service description.

Owns the single combined lifespan (gateway startup + MCP session manager) -
the MCP handler is mounted as a *plain ASGI callable*, not a sub-app with its
own lifespan, because Starlette does not forward lifespan events to mounted
sub-apps (verified empirically; see gateway.server.create_mcp_asgi_handler).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from atc_core.api import api_router, ws_router
from atc_core.approval import ApprovalManager
from atc_core.events import EventBus
from atc_core.gateway import Gateway, create_mcp_asgi_handler
from atc_core.narrator import Narrator
from atc_core.store import Store


def build_full_app(
    *,
    gateway: Gateway,
    store: Store,
    approval_manager: ApprovalManager,
    event_bus: EventBus,
    narrator: Narrator | None = None,
    static_dir: str | Path | None = None,
) -> FastAPI:
    handle_streamable_http, session_manager = create_mcp_asgi_handler(gateway)

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        await gateway.startup()
        async with session_manager.run():
            yield

    app = FastAPI(lifespan=lifespan)
    app.state.store = store
    app.state.approval_manager = approval_manager
    app.state.event_bus = event_bus
    app.state.narrator = narrator

    app.mount("/mcp", handle_streamable_http)
    app.include_router(api_router)
    app.include_router(ws_router)

    # Mounted last so it never shadows /api, /mcp, /ws. Optional so the app
    # is still constructible (and testable) before the UI exists.
    if static_dir is not None and Path(static_dir).is_dir():
        app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="ui")

    return app
