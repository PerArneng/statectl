from __future__ import annotations

from pathlib import Path

from statectl._interfaces.process import ProcessResult
from statectl._state_changer import ExistingState
from statectl._statechangers import (
    Branch,
    Commit,
    EnsureGitRepoClonedParameters,
    EnsureGitRepoClonedStateChanger,
)
from tests.fakes.in_memory_file_system import InMemoryFileSystem
from tests.fakes.scripted_process_runner import ScriptedProcessRunner


_URL = "https://example.com/foo.git"
_DEST = Path("/work/foo")


def _changer(
    fs: InMemoryFileSystem,
    pr: ScriptedProcessRunner,
    **overrides: object,
) -> EnsureGitRepoClonedStateChanger:
    params = EnsureGitRepoClonedParameters(
        repo_url=overrides.get("repo_url", _URL),  # type: ignore[arg-type]
        dest_dir=overrides.get("dest_dir", _DEST),  # type: ignore[arg-type]
        ref=overrides.get("ref", Branch(name="main")),  # type: ignore[arg-type]
        shallow=bool(overrides.get("shallow", False)),
        update_existing=bool(overrides.get("update_existing", True)),
    )
    return EnsureGitRepoClonedStateChanger(params, file_system=fs, process_runner=pr)


def _ok(stdout: str = "") -> ProcessResult:
    return ProcessResult(exit_code=0, stdout=stdout, stderr="", duration_ms=0)


def _err(stderr: str = "") -> ProcessResult:
    return ProcessResult(exit_code=1, stdout="", stderr=stderr, duration_ms=0)


def test_invalid_when_git_missing_collects_all_issues() -> None:
    fs = InMemoryFileSystem()
    pr = ScriptedProcessRunner()  # no git registered
    ch = _changer(
        fs,
        pr,
        repo_url="",
        ref=Commit(sha="notvalidsha"),
    )

    a = ch.assess_state()

    assert a.state is ExistingState.INVALID
    assert any("git binary not on PATH" in i for i in a.issues)
    assert any("repo_url is empty" in i for i in a.issues)
    assert any("invalid commit SHA" in i for i in a.issues)


def test_invalid_when_repo_url_not_recognised() -> None:
    fs = InMemoryFileSystem()
    pr = ScriptedProcessRunner()
    pr.register_executable("git")
    ch = _changer(fs, pr, repo_url="not a url")

    a = ch.assess_state()

    assert a.state is ExistingState.INVALID
    assert any("not a recognised git URL" in i for i in a.issues)


def test_invalid_when_commit_sha_wrong_length() -> None:
    fs = InMemoryFileSystem()
    pr = ScriptedProcessRunner()
    pr.register_executable("git")
    ch = _changer(fs, pr, ref=Commit(sha="abc"))

    a = ch.assess_state()

    assert a.state is ExistingState.INVALID
    assert any("invalid commit SHA" in i for i in a.issues)


def test_invalid_when_dest_exists_without_dot_git() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"))
    fs.add_dir(_DEST)
    pr = ScriptedProcessRunner()
    pr.register_executable("git")
    ch = _changer(fs, pr)

    a = ch.assess_state()

    assert a.state is ExistingState.INVALID
    assert any("not a git repo" in i for i in a.issues)


def test_invalid_when_origin_url_mismatch() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"))
    fs.add_dir(_DEST)
    fs.add_dir(_DEST / ".git")
    pr = ScriptedProcessRunner()
    pr.register_executable("git")
    pr.register(
        ("git", "-C", str(_DEST), "remote", "get-url", "origin"),
        _ok("https://example.com/other.git\n"),
    )
    ch = _changer(fs, pr)

    a = ch.assess_state()

    assert a.state is ExistingState.INVALID
    assert any("origin URL mismatch" in i for i in a.issues)


def test_invalid_when_origin_get_url_fails() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"))
    fs.add_dir(_DEST)
    fs.add_dir(_DEST / ".git")
    pr = ScriptedProcessRunner()
    pr.register_executable("git")
    pr.register(
        ("git", "-C", str(_DEST), "remote", "get-url", "origin"),
        _err("no such remote"),
    )
    ch = _changer(fs, pr)

    a = ch.assess_state()

    assert a.state is ExistingState.INVALID
    assert any("could not read origin URL" in i for i in a.issues)


def _scripts_for_existing_clean_repo(
    pr: ScriptedProcessRunner, head_sha: str, branch: str = "main"
) -> None:
    pr.register(
        ("git", "-C", str(_DEST), "remote", "get-url", "origin"),
        _ok(_URL + "\n"),
    )
    pr.register(
        ("git", "-C", str(_DEST), "status", "--porcelain"), _ok("")
    )
    pr.register(
        ("git", "-C", str(_DEST), "branch", "--show-current"),
        _ok(branch + "\n"),
    )
    pr.register(
        ("git", "-C", str(_DEST), "rev-parse", "HEAD"),
        _ok(head_sha + "\n"),
    )


def test_invalid_when_head_mismatch_and_update_existing_false() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"))
    fs.add_dir(_DEST)
    fs.add_dir(_DEST / ".git")
    pr = ScriptedProcessRunner()
    pr.register_executable("git")
    _scripts_for_existing_clean_repo(pr, head_sha="a" * 40, branch="dev")
    # branch.show-current returns "dev" not "main" so head_matches → False
    ch = _changer(fs, pr, update_existing=False)

    a = ch.assess_state()

    assert a.state is ExistingState.INVALID
    assert any("update_existing=False" in i for i in a.issues)


def test_invalid_when_dirty_and_update_existing_true() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"))
    fs.add_dir(_DEST)
    fs.add_dir(_DEST / ".git")
    pr = ScriptedProcessRunner()
    pr.register_executable("git")
    pr.register(
        ("git", "-C", str(_DEST), "remote", "get-url", "origin"),
        _ok(_URL + "\n"),
    )
    pr.register(
        ("git", "-C", str(_DEST), "status", "--porcelain"),
        _ok(" M file\n"),
    )
    pr.register(
        ("git", "-C", str(_DEST), "branch", "--show-current"),
        _ok("dev\n"),
    )
    ch = _changer(fs, pr, update_existing=True)

    a = ch.assess_state()

    assert a.state is ExistingState.INVALID
    assert any("uncommitted changes" in i for i in a.issues)
