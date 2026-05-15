from __future__ import annotations

import pytest

from statectl._interfaces.fs import FsIoError
from statectl._interfaces.process import (
    ProcessDecodeError,
    ProcessLaunchError,
    ProcessNotFound,
    ProcessTimeout,
)
from statectl._state_changer import ResultStatus
from tests.fakes.failing_file_system import FailingFileSystem
from tests.fakes.failing_process_runner import FailingProcessRunner
from tests.statechangers._launchd_helpers import (
    USER_PLIST_PATH,
    make_rig,
)


@pytest.mark.parametrize(
    "error,expected_code",
    [
        (ProcessNotFound("not found"), "LAUNCHCTL_NOT_FOUND"),
        (ProcessTimeout("timed out"), "PROCESS_TIMEOUT"),
        (ProcessDecodeError("decode"), "PROCESS_DECODE_ERROR"),
        (ProcessLaunchError("launch"), "PROCESS_LAUNCH_ERROR"),
    ],
)
def test_transition_maps_process_errors_to_codes(error, expected_code: str) -> None:
    rig = make_rig()
    pr = FailingProcessRunner(rig.pr)
    pr.fail("run", error)

    changer = rig.changer()
    result = type(changer)(
        changer.params,
        file_system=rig.fs,
        process_runner=pr,
        env=rig.env,
    ).transition()

    assert result.status is ResultStatus.FAILURE
    assert result.code == expected_code


def test_transition_write_failed_when_fs_raises() -> None:
    rig = make_rig()
    fs = FailingFileSystem(rig.fs)
    fs.fail(
        "write_text_file",
        FsIoError("disk full", path=USER_PLIST_PATH),
    )

    changer = rig.changer()
    result = type(changer)(
        changer.params,
        file_system=fs,
        process_runner=rig.pr,
        env=rig.env,
    ).transition()

    assert result.status is ResultStatus.FAILURE
    assert result.code == "WRITE_FAILED"


def test_unexpected_exception_propagates() -> None:
    """RuntimeError from a capability is not caught — it surfaces as a bug."""
    rig = make_rig()
    pr = FailingProcessRunner(rig.pr)
    pr.fail("run", RuntimeError("not a typed error"))

    changer = rig.changer()
    with pytest.raises(RuntimeError):
        type(changer)(
            changer.params,
            file_system=rig.fs,
            process_runner=pr,
            env=rig.env,
        ).transition()
