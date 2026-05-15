from __future__ import annotations

from pathlib import Path

import pytest

from statectl._interfaces.process import (
    ProcessDecodeError,
    ProcessLaunchError,
    ProcessNotFound,
    ProcessTimeout,
)
from statectl._state_changer import ExistingState
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


def _make() -> tuple[InMemoryFileSystem, ScriptedProcessRunner]:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/work"))
    fs.add_dir(_DEST)
    fs.add_dir(_DEST / ".git")
    pr = ScriptedProcessRunner()
    pr.register_executable("git")
    return fs, pr


@pytest.mark.parametrize(
    "error",
    [
        ProcessNotFound("missing", argv=("git",)),
        ProcessTimeout("timed out", argv=("git",)),
        ProcessDecodeError("decode", argv=("git",)),
        ProcessLaunchError("launch", argv=("git",)),
    ],
)
def test_probe_errors_become_invalid_not_raise(error: BaseException) -> None:
    fs, inner = _make()
    pr = FailingProcessRunner(inner)
    pr.fail("run", error)
    ch = EnsureGitRepoClonedStateChanger(
        EnsureGitRepoClonedParameters(
            repo_url=_URL, dest_dir=_DEST, ref=Branch(name="main")
        ),
        file_system=fs,
        process_runner=pr,
    )

    a = ch.assess_state()

    assert a.state is ExistingState.INVALID
    assert a.issues
