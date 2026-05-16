from __future__ import annotations

from pathlib import Path
from typing import Mapping, Sequence, override

import pytest

from statectl._interfaces.fs import FsIoError
from statectl._interfaces.process import (
    ProcessLaunchError,
    ProcessNotFound,
    ProcessResult,
    ProcessRunner,
    ProcessTimeout,
)
from statectl._state_changer import ResultStatus
from tests.fakes.failing_file_system import FailingFileSystem
from tests.statechangers._launchd_helpers import (
    DEFAULT_LABEL,
    USER_AGENTS_DIR,
    make_changer,
    make_fs_with_user_agents_dir,
    make_pr_with_launchctl,
)


def test_write_failed_when_filesystem_write_raises() -> None:
    inner = make_fs_with_user_agents_dir()
    fs = FailingFileSystem(inner)
    fs.fail(
        "write_text_file",
        FsIoError("disk full"),
        path=USER_AGENTS_DIR / f"{DEFAULT_LABEL}.plist",
    )

    pr = make_pr_with_launchctl()
    result = make_changer(fs=fs, pr=pr).transition()  # type: ignore[arg-type]
    assert result.status is ResultStatus.FAILURE
    assert result.code == "WRITE_FAILED"


@pytest.mark.parametrize(
    "exc",
    [
        ProcessNotFound("launchctl gone", argv=("launchctl",)),
        ProcessTimeout("timed out", argv=("launchctl",)),
        ProcessLaunchError("eacces", argv=("launchctl",)),
    ],
)
def test_launchctl_errors_map_to_launchctl_load_failed(exc: Exception) -> None:
    fs = make_fs_with_user_agents_dir()
    raise_exc = exc

    class _RaisingPr(ProcessRunner):
        @override
        def which(self, name: str) -> Path | None:
            return Path("/usr/bin/launchctl") if name == "launchctl" else None

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
            raise raise_exc

    result = make_changer(fs=fs, pr=_RaisingPr()).transition()
    assert result.status is ResultStatus.FAILURE
    assert result.code == "LAUNCHCTL_LOAD_FAILED"


def test_unexpected_exception_propagates_from_transition() -> None:
    fs = make_fs_with_user_agents_dir()

    class _BrokenPr(ProcessRunner):
        @override
        def which(self, name: str) -> Path | None:
            return Path("/usr/bin/launchctl")

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
            raise RuntimeError("unexpected")

    with pytest.raises(RuntimeError):
        make_changer(fs=fs, pr=_BrokenPr()).transition()


def test_bootstrap_nonzero_with_legacy_load_failure_returns_launchctl_load_failed() -> None:
    fs = make_fs_with_user_agents_dir()
    pr = make_pr_with_launchctl()
    pr.register(
        ("launchctl", "bootstrap"),
        ProcessResult(exit_code=1, stdout="", stderr="nope", duration_ms=1),
    )
    pr.register(
        ("launchctl", "load"),
        ProcessResult(exit_code=1, stdout="", stderr="also nope", duration_ms=1),
    )
    result = make_changer(fs=fs, pr=pr).transition()
    assert result.status is ResultStatus.FAILURE
    assert result.code == "LAUNCHCTL_LOAD_FAILED"
