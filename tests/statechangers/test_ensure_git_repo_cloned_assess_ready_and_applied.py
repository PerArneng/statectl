from __future__ import annotations

from pathlib import Path

from statectl._interfaces.process import ProcessResult
from statectl._state_changer import ExistingState
from statectl._statechangers import (
    Branch,
    Commit,
    EnsureGitRepoClonedParameters,
    EnsureGitRepoClonedStateChanger,
    Tag,
)
from tests.fakes.in_memory_file_system import InMemoryFileSystem
from tests.fakes.scripted_process_runner import ScriptedProcessRunner


_URL = "https://example.com/foo.git"
_DEST = Path("/work/foo")


def _ok(stdout: str = "") -> ProcessResult:
    return ProcessResult(exit_code=0, stdout=stdout, stderr="", duration_ms=0)


def _ready_rig() -> tuple[InMemoryFileSystem, ScriptedProcessRunner]:
    fs = InMemoryFileSystem()
    pr = ScriptedProcessRunner()
    pr.register_executable("git")
    return fs, pr


def _ready_when_dest_absent() -> None:  # docstring helper
    pass


def test_ready_when_dest_absent() -> None:
    fs, pr = _ready_rig()
    ch = EnsureGitRepoClonedStateChanger(
        EnsureGitRepoClonedParameters(
            repo_url=_URL, dest_dir=_DEST, ref=Branch(name="main")
        ),
        file_system=fs,
        process_runner=pr,
    )

    a = ch.assess_state()

    assert a.state is ExistingState.READY


def _add_existing_repo(fs: InMemoryFileSystem) -> None:
    fs.add_dir(Path("/work"))
    fs.add_dir(_DEST)
    fs.add_dir(_DEST / ".git")


def test_already_applied_branch_up_to_date() -> None:
    fs, pr = _ready_rig()
    _add_existing_repo(fs)
    pr.register(
        ("git", "-C", str(_DEST), "remote", "get-url", "origin"),
        _ok(_URL + "\n"),
    )
    pr.register(
        ("git", "-C", str(_DEST), "status", "--porcelain"), _ok("")
    )
    pr.register(
        ("git", "-C", str(_DEST), "branch", "--show-current"),
        _ok("main\n"),
    )
    pr.register(
        ("git", "-C", str(_DEST), "rev-parse", "main"),
        _ok("a" * 40 + "\n"),
    )
    pr.register(
        ("git", "-C", str(_DEST), "rev-parse", "origin/main"),
        _ok("a" * 40 + "\n"),
    )

    ch = EnsureGitRepoClonedStateChanger(
        EnsureGitRepoClonedParameters(
            repo_url=_URL, dest_dir=_DEST, ref=Branch(name="main")
        ),
        file_system=fs,
        process_runner=pr,
    )

    a = ch.assess_state()

    assert a.state is ExistingState.ALREADY_APPLIED


def test_already_applied_tag_match() -> None:
    fs, pr = _ready_rig()
    _add_existing_repo(fs)
    pr.register(
        ("git", "-C", str(_DEST), "remote", "get-url", "origin"),
        _ok(_URL + "\n"),
    )
    pr.register(
        ("git", "-C", str(_DEST), "status", "--porcelain"), _ok("")
    )
    pr.register(
        ("git", "-C", str(_DEST), "rev-parse", "HEAD"),
        _ok("a" * 40 + "\n"),
    )
    pr.register(
        ("git", "-C", str(_DEST), "rev-parse", "v1.0"),
        _ok("a" * 40 + "\n"),
    )

    ch = EnsureGitRepoClonedStateChanger(
        EnsureGitRepoClonedParameters(
            repo_url=_URL, dest_dir=_DEST, ref=Tag(name="v1.0")
        ),
        file_system=fs,
        process_runner=pr,
    )

    a = ch.assess_state()

    assert a.state is ExistingState.ALREADY_APPLIED


def test_already_applied_commit_match() -> None:
    fs, pr = _ready_rig()
    _add_existing_repo(fs)
    sha = "b" * 40
    pr.register(
        ("git", "-C", str(_DEST), "remote", "get-url", "origin"),
        _ok(_URL + "\n"),
    )
    pr.register(
        ("git", "-C", str(_DEST), "status", "--porcelain"), _ok("")
    )
    pr.register(
        ("git", "-C", str(_DEST), "rev-parse", "HEAD"),
        _ok(sha + "\n"),
    )

    ch = EnsureGitRepoClonedStateChanger(
        EnsureGitRepoClonedParameters(
            repo_url=_URL, dest_dir=_DEST, ref=Commit(sha=sha)
        ),
        file_system=fs,
        process_runner=pr,
    )

    a = ch.assess_state()

    assert a.state is ExistingState.ALREADY_APPLIED


def test_ready_to_update_when_clean_and_head_mismatch_and_update_existing_true() -> None:
    fs, pr = _ready_rig()
    _add_existing_repo(fs)
    pr.register(
        ("git", "-C", str(_DEST), "remote", "get-url", "origin"),
        _ok(_URL + "\n"),
    )
    pr.register(
        ("git", "-C", str(_DEST), "status", "--porcelain"), _ok("")
    )
    pr.register(
        ("git", "-C", str(_DEST), "branch", "--show-current"),
        _ok("dev\n"),
    )

    ch = EnsureGitRepoClonedStateChanger(
        EnsureGitRepoClonedParameters(
            repo_url=_URL,
            dest_dir=_DEST,
            ref=Branch(name="main"),
            update_existing=True,
        ),
        file_system=fs,
        process_runner=pr,
    )

    a = ch.assess_state()

    assert a.state is ExistingState.READY


def test_branch_not_already_applied_when_local_behind_remote() -> None:
    fs, pr = _ready_rig()
    _add_existing_repo(fs)
    pr.register(
        ("git", "-C", str(_DEST), "remote", "get-url", "origin"),
        _ok(_URL + "\n"),
    )
    pr.register(
        ("git", "-C", str(_DEST), "status", "--porcelain"), _ok("")
    )
    pr.register(
        ("git", "-C", str(_DEST), "branch", "--show-current"),
        _ok("main\n"),
    )
    pr.register(
        ("git", "-C", str(_DEST), "rev-parse", "main"),
        _ok("a" * 40 + "\n"),
    )
    pr.register(
        ("git", "-C", str(_DEST), "rev-parse", "origin/main"),
        _ok("c" * 40 + "\n"),
    )

    ch = EnsureGitRepoClonedStateChanger(
        EnsureGitRepoClonedParameters(
            repo_url=_URL,
            dest_dir=_DEST,
            ref=Branch(name="main"),
            update_existing=True,
        ),
        file_system=fs,
        process_runner=pr,
    )

    a = ch.assess_state()

    assert a.state is ExistingState.READY
