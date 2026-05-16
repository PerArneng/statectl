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
from tests.statechangers._systemd_helpers import (
    DEFAULT_UNIT,
    USER_UNIT_DIR,
    make_changer,
    make_fs_with_user_unit_dir,
    make_pr_with_systemctl,
)


def test_write_failed_when_filesystem_write_raises() -> None:
    inner = make_fs_with_user_unit_dir()
    fs = FailingFileSystem(inner)
    fs.fail(
        "write_text_file",
        FsIoError("disk full"),
        path=USER_UNIT_DIR / DEFAULT_UNIT,
    )

    pr = make_pr_with_systemctl()
    result = make_changer(fs=fs, pr=pr).transition()  # type: ignore[arg-type]
    assert result.status is ResultStatus.FAILURE
    assert result.code == "WRITE_FAILED"


def test_daemon_reload_failed_on_nonzero_exit() -> None:
    fs = make_fs_with_user_unit_dir()
    pr = make_pr_with_systemctl()
    pr.register(
        ("systemctl", "--user", "daemon-reload"),
        ProcessResult(exit_code=1, stdout="", stderr="boom", duration_ms=1),
    )
    result = make_changer(fs=fs, pr=pr).transition()
    assert result.status is ResultStatus.FAILURE
    assert result.code == "DAEMON_RELOAD_FAILED"


def test_systemctl_enable_failed_on_nonzero_exit() -> None:
    fs = make_fs_with_user_unit_dir()
    pr = make_pr_with_systemctl()
    pr.register(
        ("systemctl", "--user", "enable"),
        ProcessResult(exit_code=1, stdout="", stderr="no", duration_ms=1),
    )
    result = make_changer(fs=fs, pr=pr).transition()
    assert result.status is ResultStatus.FAILURE
    assert result.code == "SYSTEMCTL_ENABLE_FAILED"


def test_systemctl_start_failed_on_nonzero_exit() -> None:
    fs = make_fs_with_user_unit_dir()
    pr = make_pr_with_systemctl()
    pr.register(
        ("systemctl", "--user", "start"),
        ProcessResult(exit_code=1, stdout="", stderr="no", duration_ms=1),
    )
    result = make_changer(fs=fs, pr=pr).transition()
    assert result.status is ResultStatus.FAILURE
    assert result.code == "SYSTEMCTL_START_FAILED"


@pytest.mark.parametrize(
    "exc,expected_code",
    [
        (ProcessNotFound("gone", argv=("systemctl",)), "DAEMON_RELOAD_FAILED"),
        (ProcessTimeout("timed out", argv=("systemctl",)), "DAEMON_RELOAD_FAILED"),
        (ProcessLaunchError("eacces", argv=("systemctl",)), "DAEMON_RELOAD_FAILED"),
    ],
)
def test_typed_process_errors_map_to_failure_codes(
    exc: Exception, expected_code: str
) -> None:
    fs = make_fs_with_user_unit_dir()
    raise_exc = exc

    class _RaisingPr(ProcessRunner):
        @override
        def which(self, name: str) -> Path | None:
            return Path("/usr/bin/systemctl") if name == "systemctl" else None

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
    assert result.code == expected_code


def test_unexpected_exception_propagates_from_transition() -> None:
    fs = make_fs_with_user_unit_dir()

    class _BrokenPr(ProcessRunner):
        @override
        def which(self, name: str) -> Path | None:
            return Path("/usr/bin/systemctl")

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
