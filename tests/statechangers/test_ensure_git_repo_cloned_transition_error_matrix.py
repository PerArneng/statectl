from __future__ import annotations

from pathlib import Path

import pytest

from statectl._interfaces.process import (
    ProcessDecodeError,
    ProcessLaunchError,
    ProcessNotFound,
    ProcessTimeout,
)
from statectl._state_changer import ResultStatus
from statectl._statechangers import (
    Branch,
    EnsureGitRepoClonedParameters,
    EnsureGitRepoClonedStateChanger,
)
from tests.fakes.failing_process_runner import FailingProcessRunner
from tests.fakes.in_memory_file_system import InMemoryFileSystem
from tests.fakes.scripted_process_runner import ScriptedProcessRunner


_URL = "https://example.com/foo.git"
_DEST = Path("/work/foo")


def _inner() -> ScriptedProcessRunner:
    pr = ScriptedProcessRunner()
    pr.register_executable("git")
    return pr


@pytest.mark.parametrize(
    "error, expected_code",
    [
        (ProcessNotFound("missing", argv=("git",)), "GIT_NOT_FOUND"),
        (ProcessTimeout("timed out", argv=("git",)), "PROCESS_TIMEOUT"),
        (ProcessDecodeError("decode", argv=("git",)), "PROCESS_DECODE_ERROR"),
        (ProcessLaunchError("launch", argv=("git",)), "PROCESS_LAUNCH_ERROR"),
    ],
)
def test_typed_errors_map_to_codes(
    error: BaseException, expected_code: str
) -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"))
    pr = FailingProcessRunner(_inner())
    pr.fail("run", error)
    ch = EnsureGitRepoClonedStateChanger(
        EnsureGitRepoClonedParameters(
            repo_url=_URL, dest_dir=_DEST, ref=Branch(name="main")
        ),
        file_system=fs,
        process_runner=pr,
    )

    result = ch.transition()

    assert result.status is ResultStatus.FAILURE
    assert result.code == expected_code


def test_unexpected_exception_propagates() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"))
    pr = FailingProcessRunner(_inner())
    pr.fail("run", RuntimeError("boom"))
    ch = EnsureGitRepoClonedStateChanger(
        EnsureGitRepoClonedParameters(
            repo_url=_URL, dest_dir=_DEST, ref=Branch(name="main")
        ),
        file_system=fs,
        process_runner=pr,
    )

    with pytest.raises(RuntimeError):
        ch.transition()
