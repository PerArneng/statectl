from __future__ import annotations

from pathlib import Path

from statectl._interfaces.process import ProcessResult
from statectl._state_changer import ExistingState, ResultStatus
from statectl._statechangers import (
    Branch,
    EnsureGitRepoClonedParameters,
    EnsureGitRepoClonedRollbackStateChanger,
)
from tests.fakes.in_memory_file_system import InMemoryFileSystem
from tests.fakes.scripted_process_runner import ScriptedProcessRunner


_URL = "https://example.com/foo.git"
_DEST = Path("/work/foo")


def _params() -> EnsureGitRepoClonedParameters:
    return EnsureGitRepoClonedParameters(
        repo_url=_URL, dest_dir=_DEST, ref=Branch(name="main")
    )


def test_rollback_already_applied_when_dest_absent() -> None:
    fs = InMemoryFileSystem()
    pr = ScriptedProcessRunner()
    pr.register_executable("git")
    inv = EnsureGitRepoClonedRollbackStateChanger(
        _params(), file_system=fs, process_runner=pr
    )

    a = inv.assess_state()

    assert a.state is ExistingState.ALREADY_APPLIED


def test_rollback_ready_when_dest_exists_clean() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"))
    fs.add_dir(_DEST)
    fs.add_dir(_DEST / ".git")
    pr = ScriptedProcessRunner()
    pr.register_executable("git")
    pr.register(
        ("git", "-C", str(_DEST), "status", "--porcelain"),
        ProcessResult(exit_code=0, stdout="", stderr="", duration_ms=0),
    )
    inv = EnsureGitRepoClonedRollbackStateChanger(
        _params(), file_system=fs, process_runner=pr
    )

    a = inv.assess_state()

    assert a.state is ExistingState.READY


def test_rollback_invalid_when_dirty() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"))
    fs.add_dir(_DEST)
    fs.add_dir(_DEST / ".git")
    pr = ScriptedProcessRunner()
    pr.register_executable("git")
    pr.register(
        ("git", "-C", str(_DEST), "status", "--porcelain"),
        ProcessResult(
            exit_code=0, stdout=" M foo.txt\n", stderr="", duration_ms=0
        ),
    )
    inv = EnsureGitRepoClonedRollbackStateChanger(
        _params(), file_system=fs, process_runner=pr
    )

    a = inv.assess_state()

    assert a.state is ExistingState.INVALID
    assert any("uncommitted changes" in i for i in a.issues)


def test_rollback_ready_when_dest_exists_without_git_dir() -> None:
    # Not a git repo — rollback can still delete the directory without checking
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"))
    fs.add_dir(_DEST)
    pr = ScriptedProcessRunner()
    pr.register_executable("git")
    inv = EnsureGitRepoClonedRollbackStateChanger(
        _params(), file_system=fs, process_runner=pr
    )

    a = inv.assess_state()

    assert a.state is ExistingState.READY


def test_rollback_transition_deletes_directory() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"))
    fs.add_dir(_DEST)
    fs.add_dir(_DEST / ".git")
    fs.add_file(_DEST / "README", content="hello")
    pr = ScriptedProcessRunner()
    pr.register_executable("git")
    inv = EnsureGitRepoClonedRollbackStateChanger(
        _params(), file_system=fs, process_runner=pr
    )

    result = inv.transition()

    assert result.status is ResultStatus.SUCCESS
    assert not fs.exists(_DEST)


def test_rollback_transition_skips_when_dir_vanishes() -> None:
    fs = InMemoryFileSystem()
    pr = ScriptedProcessRunner()
    pr.register_executable("git")
    inv = EnsureGitRepoClonedRollbackStateChanger(
        _params(), file_system=fs, process_runner=pr
    )

    result = inv.transition()

    assert result.status is ResultStatus.SKIPPED
