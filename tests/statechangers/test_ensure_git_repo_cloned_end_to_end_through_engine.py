from __future__ import annotations

from pathlib import Path
from typing import Mapping, Sequence, override

from statectl import StateCtl
from statectl._engine_result import NodeOutcome
from statectl._interfaces.process import ProcessResult
from statectl._statechangers import (
    Branch,
    EnsureGitRepoClonedParameters,
    EnsureGitRepoClonedStateChanger,
)
from tests.fakes.in_memory_file_system import InMemoryFileSystem
from tests.fakes.scripted_process_runner import ScriptedProcessRunner


_URL = "https://example.com/foo.git"
_DEST = Path("/work/foo")


class _StatefulGitRunner(ScriptedProcessRunner):
    """ScriptedProcessRunner that simulates `git clone` by creating the dest
    directory in the in-memory filesystem so post-assess sees ALREADY_APPLIED.
    """

    def __init__(self, fs: InMemoryFileSystem) -> None:
        super().__init__()
        self._fs = fs
        self.register_executable("git")
        self._head: str = "a" * 40

    @override
    def run(
        self,
        argv: Sequence[str],
        *,
        cwd: Path | None = None,
        env: Mapping[str, str] | None = None,
        stdin: str | None = None,
        timeout: float | None = None,
    ) -> ProcessResult:
        argv_t = tuple(argv)
        super().run(argv, cwd=cwd, env=env, stdin=stdin, timeout=timeout)

        if len(argv_t) >= 2 and argv_t[:2] == ("git", "clone"):
            dest_str = argv_t[-1]
            dest = Path(dest_str)
            if not self._fs.exists(dest):
                self._fs.add_dir(dest)
            if not self._fs.exists(dest / ".git"):
                self._fs.add_dir(dest / ".git")
            return ProcessResult(exit_code=0, stdout="", stderr="", duration_ms=0)

        # Post-clone queries return repo state consistent with HEAD at main.
        if argv_t[:5] == ("git", "-C", str(_DEST), "remote", "get-url"):
            return ProcessResult(exit_code=0, stdout=_URL + "\n", stderr="", duration_ms=0)
        if argv_t[:4] == ("git", "-C", str(_DEST), "status"):
            return ProcessResult(exit_code=0, stdout="", stderr="", duration_ms=0)
        if argv_t[:4] == ("git", "-C", str(_DEST), "branch"):
            return ProcessResult(exit_code=0, stdout="main\n", stderr="", duration_ms=0)
        if argv_t[:5] == ("git", "-C", str(_DEST), "rev-parse", "HEAD") or argv_t[
            :5
        ] == ("git", "-C", str(_DEST), "rev-parse", "main") or argv_t[:5] == (
            "git",
            "-C",
            str(_DEST),
            "rev-parse",
            "origin/main",
        ):
            return ProcessResult(
                exit_code=0, stdout=self._head + "\n", stderr="", duration_ms=0
            )
        if argv_t[:4] == ("git", "-C", str(_DEST), "checkout"):
            return ProcessResult(exit_code=0, stdout="", stderr="", duration_ms=0)
        return ProcessResult(exit_code=0, stdout="", stderr="", duration_ms=0)


def _params() -> EnsureGitRepoClonedParameters:
    return EnsureGitRepoClonedParameters(
        repo_url=_URL, dest_dir=_DEST, ref=Branch(name="main")
    )


def test_engine_clones_when_dest_absent() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"))
    pr = _StatefulGitRunner(fs)

    ctl = StateCtl.new(file_system=fs, process_runner=pr)
    ctl.add(EnsureGitRepoClonedStateChanger(_params(), file_system=fs, process_runner=pr))
    result = ctl.start(max_workers=1)

    assert result.ok, result.reports[0].result
    assert result.reports[0].outcome is NodeOutcome.SUCCESS


def test_engine_skips_when_already_at_ref() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"))
    fs.add_dir(_DEST)
    fs.add_dir(_DEST / ".git")
    pr = _StatefulGitRunner(fs)

    ctl = StateCtl.new(file_system=fs, process_runner=pr)
    ctl.add(EnsureGitRepoClonedStateChanger(_params(), file_system=fs, process_runner=pr))
    result = ctl.start(max_workers=1)

    assert result.ok
    assert result.reports[0].outcome is NodeOutcome.SKIPPED_ALREADY_APPLIED


def test_engine_halts_on_invalid_dest_not_a_git_repo() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"))
    fs.add_dir(_DEST)  # no .git
    pr = ScriptedProcessRunner()
    pr.register_executable("git")

    ctl = StateCtl.new(file_system=fs, process_runner=pr)
    ctl.add(EnsureGitRepoClonedStateChanger(_params(), file_system=fs, process_runner=pr))
    result = ctl.start(max_workers=1)

    assert not result.ok
    assert result.reports[0].outcome is NodeOutcome.FAILED_INVALID


def test_engine_halts_on_clone_failure() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"))
    pr = ScriptedProcessRunner()
    pr.register_executable("git")
    pr.register(
        ("git", "clone"),
        ProcessResult(exit_code=1, stdout="", stderr="net down", duration_ms=0),
    )

    ctl = StateCtl.new(file_system=fs, process_runner=pr)
    ctl.add(EnsureGitRepoClonedStateChanger(_params(), file_system=fs, process_runner=pr))
    result = ctl.start(max_workers=1)

    assert not result.ok
    assert result.reports[0].outcome is NodeOutcome.FAILED_TRANSITION
    report_result = result.reports[0].result
    assert report_result is not None
    assert report_result.code == "GIT_CLONE_FAILED"
