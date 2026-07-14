"""Path sandboxing: every fs__* call is confined to a dedicated volume root.
See PROJECT_PLAN.md S4 ("fs__read, fs__write, fs__delete on dedicated
volume"). A path like "../../etc/passwd" must never resolve outside root -
this is the actual security boundary, not just a convenience.
"""

from __future__ import annotations

from pathlib import Path


class PathEscapesSandboxError(ValueError):
    pass


def resolve_safe_path(root: Path, user_path: str) -> Path:
    """Resolves `user_path` against `root`. `user_path` is always treated as
    relative to root regardless of a leading slash - it names a location
    within the sandboxed volume, not the real host filesystem root."""
    root_resolved = root.resolve()
    candidate = (root_resolved / user_path.lstrip("/\\")).resolve()
    try:
        candidate.relative_to(root_resolved)
    except ValueError:
        raise PathEscapesSandboxError(
            f"path escapes sandboxed root: {user_path!r}"
        ) from None
    return candidate
