from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from statectl._interfaces.process import (
    ProcessDecodeError,
    ProcessError,
    ProcessLaunchError,
    ProcessNotFound,
    ProcessTimeout,
)
from statectl._state_changer import ResultStatus
from statectl._statechangers import AptUpdateParameters, AptUpdateStateChanger
from tests.fakes.in_memory_file_system import InMemoryFileSystem
from tests.fakes.scripted_clock import ScriptedClock
from tests.fakes.scripted_env import ScriptedEnv
from tests.fakes.scripted_process_runner import ScriptedProcessRunner


_LISTS = Path("/var/lib/apt/lists")


class _RaisingProcessRunner(ScriptedProcessRunner):
    def __init__(self, exc: ProcessError) -> None:
        super().__init__()
        self.register_executable("apt-get")
        self._exc = exc

    def run(self, argv: Any, **kwargs: Any) -> Any:  # type: ignore[override]
        raise self._exc


@pytest.mark.parametrize(
    "exc,expected_code",
    [
        (ProcessNotFound("apt-get vanished"), "APT_NOT_FOUND"),
        (ProcessTimeout("too slow"), "PROCESS_TIMEOUT"),
        (ProcessDecodeError("bad encoding"), "PROCESS_DECODE_ERROR"),
        (ProcessLaunchError("ENOEXEC"), "PROCESS_LAUNCH_ERROR"),
    ],
)
def test_typed_process_errors_map_to_codes(
    exc: ProcessError, expected_code: str
) -> None:
    pr = _RaisingProcessRunner(exc)
    fs = InMemoryFileSystem()
    fs.add_dir(_LISTS)
    changer = AptUpdateStateChanger(
        AptUpdateParameters(),
        process_runner=pr,
        file_system=fs,
        env=ScriptedEnv.linux(),
        clock=ScriptedClock(),
    )

    result = changer.transition()

    assert result.status is ResultStatus.FAILURE
    assert result.code == expected_code


def test_non_typed_exception_propagates() -> None:
    class _Boom(ScriptedProcessRunner):
        def __init__(self) -> None:
            super().__init__()
            self.register_executable("apt-get")

        def run(self, argv: Any, **kwargs: Any) -> Any:  # type: ignore[override]
            raise RuntimeError("unexpected")

    pr = _Boom()
    fs = InMemoryFileSystem()
    fs.add_dir(_LISTS)
    changer = AptUpdateStateChanger(
        AptUpdateParameters(),
        process_runner=pr,
        file_system=fs,
        env=ScriptedEnv.linux(),
        clock=ScriptedClock(),
    )

    with pytest.raises(RuntimeError):
        changer.transition()
