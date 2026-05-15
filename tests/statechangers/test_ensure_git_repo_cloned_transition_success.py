from __future__ import annotations

from pathlib import Path

from statectl._interfaces.process import ProcessResult
from statectl._state_changer import ResultStatus
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


def _rig() -> tuple[InMemoryFileSystem, ScriptedProcessRunner]:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"))
    pr = ScriptedProcessRunner()
    pr.register_executable("git")
    return fs, pr


def test_clone_then_checkout_when_dest_absent_non_shallow_branch() -> None:
    fs, pr = _rig()
    ch = EnsureGitRepoClonedStateChanger(
        EnsureGitRepoClonedParameters(
            repo_url=_URL, dest_dir=_DEST, ref=Branch(name="main"), shallow=False
        ),
        file_system=fs,
        process_runner=pr,
    )

    result = ch.transition()

    assert result.status is ResultStatus.SUCCESS
    argvs = [c.argv for c in pr.calls]
    assert ("git", "clone", _URL, str(_DEST)) in argvs
    assert ("git", "-C", str(_DEST), "checkout", "main") in argvs


def test_shallow_clone_with_branch_uses_depth_1_and_skips_checkout() -> None:
    fs, pr = _rig()
    ch = EnsureGitRepoClonedStateChanger(
        EnsureGitRepoClonedParameters(
            repo_url=_URL, dest_dir=_DEST, ref=Branch(name="dev"), shallow=True
        ),
        file_system=fs,
        process_runner=pr,
    )

    result = ch.transition()

    assert result.status is ResultStatus.SUCCESS
    argvs = [c.argv for c in pr.calls]
    assert (
        "git",
        "clone",
        "--depth",
        "1",
        "--branch",
        "dev",
        _URL,
        str(_DEST),
    ) in argvs
    assert ("git", "-C", str(_DEST), "checkout", "dev") not in argvs


def test_shallow_with_commit_ref_uses_full_clone_and_then_checkout() -> None:
    fs, pr = _rig()
    sha = "f" * 40
    ch = EnsureGitRepoClonedStateChanger(
        EnsureGitRepoClonedParameters(
            repo_url=_URL,
            dest_dir=_DEST,
            ref=Commit(sha=sha),
            shallow=True,
        ),
        file_system=fs,
        process_runner=pr,
    )

    result = ch.transition()

    assert result.status is ResultStatus.SUCCESS
    argvs = [c.argv for c in pr.calls]
    assert ("git", "clone", _URL, str(_DEST)) in argvs
    assert ("git", "-C", str(_DEST), "checkout", sha) in argvs


def test_clone_with_tag_ref_checks_out_tag() -> None:
    fs, pr = _rig()
    ch = EnsureGitRepoClonedStateChanger(
        EnsureGitRepoClonedParameters(
            repo_url=_URL, dest_dir=_DEST, ref=Tag(name="v1.0")
        ),
        file_system=fs,
        process_runner=pr,
    )

    result = ch.transition()

    assert result.status is ResultStatus.SUCCESS
    argvs = [c.argv for c in pr.calls]
    assert ("git", "-C", str(_DEST), "checkout", "v1.0") in argvs


def test_fetch_and_checkout_when_dest_exists_branch_ff_merge() -> None:
    fs, pr = _rig()
    fs.add_dir(_DEST)
    fs.add_dir(_DEST / ".git")
    ch = EnsureGitRepoClonedStateChanger(
        EnsureGitRepoClonedParameters(
            repo_url=_URL, dest_dir=_DEST, ref=Branch(name="main")
        ),
        file_system=fs,
        process_runner=pr,
    )

    result = ch.transition()

    assert result.status is ResultStatus.SUCCESS
    argvs = [c.argv for c in pr.calls]
    assert ("git", "-C", str(_DEST), "fetch", "origin") in argvs
    assert ("git", "-C", str(_DEST), "checkout", "main") in argvs
    assert (
        "git",
        "-C",
        str(_DEST),
        "merge",
        "--ff-only",
        "origin/main",
    ) in argvs


def test_fetch_and_checkout_when_dest_exists_commit_no_ff() -> None:
    fs, pr = _rig()
    fs.add_dir(_DEST)
    fs.add_dir(_DEST / ".git")
    sha = "0" * 40
    ch = EnsureGitRepoClonedStateChanger(
        EnsureGitRepoClonedParameters(
            repo_url=_URL, dest_dir=_DEST, ref=Commit(sha=sha)
        ),
        file_system=fs,
        process_runner=pr,
    )

    result = ch.transition()

    assert result.status is ResultStatus.SUCCESS
    argvs = [c.argv for c in pr.calls]
    assert not any(a[3:5] == ("merge", "--ff-only") for a in argvs if len(a) > 5)


def test_clone_failure_returns_git_clone_failed() -> None:
    fs, pr = _rig()
    pr.register(
        ("git", "clone"),
        ProcessResult(exit_code=128, stdout="", stderr="boom", duration_ms=0),
    )
    ch = EnsureGitRepoClonedStateChanger(
        EnsureGitRepoClonedParameters(
            repo_url=_URL, dest_dir=_DEST, ref=Branch(name="main")
        ),
        file_system=fs,
        process_runner=pr,
    )

    result = ch.transition()

    assert result.status is ResultStatus.FAILURE
    assert result.code == "GIT_CLONE_FAILED"
    assert result.details["stderr"] == "boom"
    assert result.details["exit_code"] == "128"


def test_fetch_failure_returns_git_fetch_failed() -> None:
    fs, pr = _rig()
    fs.add_dir(_DEST)
    fs.add_dir(_DEST / ".git")
    pr.register(
        ("git", "-C", str(_DEST), "fetch", "origin"),
        ProcessResult(exit_code=1, stdout="", stderr="net", duration_ms=0),
    )
    ch = EnsureGitRepoClonedStateChanger(
        EnsureGitRepoClonedParameters(
            repo_url=_URL, dest_dir=_DEST, ref=Branch(name="main")
        ),
        file_system=fs,
        process_runner=pr,
    )

    result = ch.transition()

    assert result.status is ResultStatus.FAILURE
    assert result.code == "GIT_FETCH_FAILED"


def test_checkout_failure_returns_git_checkout_failed() -> None:
    fs, pr = _rig()
    fs.add_dir(_DEST)
    fs.add_dir(_DEST / ".git")
    pr.register(
        ("git", "-C", str(_DEST), "checkout"),
        ProcessResult(exit_code=1, stdout="", stderr="nope", duration_ms=0),
    )
    ch = EnsureGitRepoClonedStateChanger(
        EnsureGitRepoClonedParameters(
            repo_url=_URL, dest_dir=_DEST, ref=Branch(name="main")
        ),
        file_system=fs,
        process_runner=pr,
    )

    result = ch.transition()

    assert result.status is ResultStatus.FAILURE
    assert result.code == "GIT_CHECKOUT_FAILED"
