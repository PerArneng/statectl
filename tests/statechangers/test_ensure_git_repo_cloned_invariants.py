from __future__ import annotations

from pathlib import Path

import pytest

from statectl._state_changer import RollbackableStateChanger, StateChanger
from statectl._statechangers import (
    Branch,
    Commit,
    EnsureGitRepoClonedParameters,
    EnsureGitRepoClonedRollbackStateChanger,
    EnsureGitRepoClonedStateChanger,
    Tag,
)
from tests.fakes.in_memory_file_system import InMemoryFileSystem
from tests.fakes.scripted_process_runner import ScriptedProcessRunner


def _params(ref: Branch | Tag | Commit | None = None) -> EnsureGitRepoClonedParameters:
    return EnsureGitRepoClonedParameters(
        repo_url="https://example.com/foo.git",
        dest_dir=Path("/work/foo"),
        ref=ref or Branch(name="main"),
    )


def _rig() -> tuple[InMemoryFileSystem, ScriptedProcessRunner]:
    fs = InMemoryFileSystem()
    pr = ScriptedProcessRunner()
    pr.register_executable("git")
    return fs, pr


def test_is_rollbackable_state_changer() -> None:
    fs, pr = _rig()
    ch = EnsureGitRepoClonedStateChanger(_params(), file_system=fs, process_runner=pr)
    assert isinstance(ch, RollbackableStateChanger)


def test_rollback_returns_plain_state_changer() -> None:
    fs, pr = _rig()
    ch = EnsureGitRepoClonedStateChanger(_params(), file_system=fs, process_runner=pr)
    inverse = ch.rollback()
    assert isinstance(inverse, StateChanger)
    assert not isinstance(inverse, RollbackableStateChanger)
    assert isinstance(inverse, EnsureGitRepoClonedRollbackStateChanger)


def test_parameters_are_frozen() -> None:
    params = _params()
    with pytest.raises(Exception):
        params.repo_url = "x"  # type: ignore[misc]


def test_branch_is_frozen() -> None:
    b = Branch(name="main")
    with pytest.raises(Exception):
        b.name = "dev"  # type: ignore[misc]


def test_name_encodes_dest_and_ref_token() -> None:
    fs, pr = _rig()
    ch = EnsureGitRepoClonedStateChanger(
        _params(Branch(name="dev")), file_system=fs, process_runner=pr
    )
    assert ch.name() == "ensure-git-repo-cloned:/work/foo@dev"


def test_name_encodes_commit_sha() -> None:
    fs, pr = _rig()
    sha = "a" * 40
    ch = EnsureGitRepoClonedStateChanger(
        _params(Commit(sha=sha)), file_system=fs, process_runner=pr
    )
    assert ch.name() == f"ensure-git-repo-cloned:/work/foo@{sha}"


def test_rollback_name_encodes_dest() -> None:
    fs, pr = _rig()
    inv = EnsureGitRepoClonedRollbackStateChanger(
        _params(), file_system=fs, process_runner=pr
    )
    assert inv.name() == "ensure-git-repo-cloned-rollback:/work/foo"
