"""In-memory mock repo. See PROJECT_PLAN.md S4: "Mock MCP server (in-memory
repo; git__push, git__force_push)". No real git plumbing - this exists to
give agents something demo-able to push to, and to let a force-push visibly
rewrite history on camera.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class InMemoryRepo:
    branches: dict[str, list[str]] = field(default_factory=lambda: {"main": []})

    def push(self, branch: str, message: str) -> str:
        commits = self.branches.setdefault(branch, [])
        commits.append(message)
        return f"pushed to {branch!r}: {len(commits)} commit(s) total"

    def force_push(self, branch: str, message: str) -> str:
        previous_count = len(self.branches.get(branch, []))
        self.branches[branch] = [message]
        return f"force-pushed to {branch!r}: history rewritten ({previous_count} commit(s) replaced with 1)"
