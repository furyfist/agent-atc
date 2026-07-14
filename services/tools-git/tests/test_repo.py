"""Unit tests for the in-memory mock repo."""

from __future__ import annotations

from tools_git.repo import InMemoryRepo


def test_new_repo_has_empty_main_branch() -> None:
    repo = InMemoryRepo()
    assert repo.branches == {"main": []}


def test_push_appends_to_branch() -> None:
    repo = InMemoryRepo()
    result = repo.push("main", "add feature")
    assert "1 commit" in result
    assert repo.branches["main"] == ["add feature"]

    repo.push("main", "fix bug")
    assert repo.branches["main"] == ["add feature", "fix bug"]


def test_push_creates_new_branch_if_missing() -> None:
    repo = InMemoryRepo()
    repo.push("feature/x", "wip")
    assert repo.branches["feature/x"] == ["wip"]
    assert repo.branches["main"] == []  # untouched


def test_force_push_rewrites_history() -> None:
    repo = InMemoryRepo()
    repo.push("main", "commit 1")
    repo.push("main", "commit 2")
    repo.push("main", "commit 3")

    result = repo.force_push("main", "rewritten history")
    assert "3 commit(s) replaced" in result
    assert repo.branches["main"] == ["rewritten history"]


def test_force_push_on_new_branch() -> None:
    repo = InMemoryRepo()
    result = repo.force_push("new-branch", "first commit")
    assert "0 commit(s) replaced" in result
    assert repo.branches["new-branch"] == ["first commit"]
