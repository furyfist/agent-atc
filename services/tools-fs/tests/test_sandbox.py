"""Unit tests for the path-sandboxing logic - the actual security boundary."""

from __future__ import annotations

from pathlib import Path

import pytest

from tools_fs.sandbox import PathEscapesSandboxError, resolve_safe_path


@pytest.fixture
def root(tmp_path: Path) -> Path:
    return tmp_path / "volume"


def test_simple_relative_path_resolves_within_root(root: Path) -> None:
    result = resolve_safe_path(root, "notes.txt")
    assert result == (root / "notes.txt").resolve()


def test_nested_relative_path_resolves_within_root(root: Path) -> None:
    result = resolve_safe_path(root, "sub/dir/notes.txt")
    assert result == (root / "sub" / "dir" / "notes.txt").resolve()


def test_leading_slash_is_treated_as_relative_to_root(root: Path) -> None:
    result = resolve_safe_path(root, "/notes.txt")
    assert result == (root / "notes.txt").resolve()


@pytest.mark.parametrize(
    "traversal",
    [
        "../outside.txt",
        "../../outside.txt",
        "sub/../../outside.txt",
        "../../../../../../etc/passwd",
    ],
)
def test_parent_traversal_is_blocked(root: Path, traversal: str) -> None:
    with pytest.raises(PathEscapesSandboxError):
        resolve_safe_path(root, traversal)


def test_absolute_path_outside_root_is_blocked(root: Path, tmp_path: Path) -> None:
    outside = tmp_path / "elsewhere" / "secret.txt"
    with pytest.raises(PathEscapesSandboxError):
        resolve_safe_path(root, str(outside))
