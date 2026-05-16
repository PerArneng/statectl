from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from statectl import NodeOutcome, StateCtl
from statectl._interfaces.process import ProcessResult
from statectl._modules import DefaultLogger, InMemoryVariableRegistry, RealHashing
from statectl._statechangers import AptUpdateParameters, AptUpdateStateChanger
from tests.fakes.in_memory_file_system import InMemoryFileSystem
from tests.fakes.scripted_archive import ScriptedArchive
from tests.fakes.scripted_clock import ScriptedClock
from tests.fakes.scripted_env import ScriptedEnv
from tests.fakes.scripted_http_client import ScriptedHttpClient
from tests.fakes.scripted_process_runner import ScriptedProcessRunner


_LISTS = Path("/var/lib/apt/lists")
_NOW = datetime(2026, 5, 16, 12, 0, 0, tzinfo=timezone.utc)


def _clock_at(now: datetime) -> ScriptedClock:
    clock = ScriptedClock()
    clock.set_now(now)
    return clock


class _MtimeBumpingRunner(ScriptedProcessRunner):
    """ScriptedProcessRunner that bumps a file's mtime after each run, used
    to simulate a real command's filesystem side effects in engine tests.
    """

    def __init__(
        self, inner_fs: InMemoryFileSystem, path: Path, new_mtime: datetime
    ) -> None:
        super().__init__()
        self._fs = inner_fs
        self._path = path
        self._new_mtime = new_mtime

    def run(self, argv: Any, **kwargs: Any) -> Any:  # type: ignore[override]
        result = super().run(argv, **kwargs)
        self._fs.set_mtime(self._path, self._new_mtime)
        return result


def _engine(
    fs: InMemoryFileSystem,
    pr: ScriptedProcessRunner,
    clock: ScriptedClock,
) -> StateCtl:
    return StateCtl(
        logger=DefaultLogger("test"),
        file_system=fs,
        process_runner=pr,
        http_client=ScriptedHttpClient(),
        env=ScriptedEnv.linux(),
        archive=ScriptedArchive(),
        hashing=RealHashing(),
        clock=clock,
        variable_registry=InMemoryVariableRegistry(),
    )


def test_engine_skips_when_lists_are_fresh() -> None:
    pr = ScriptedProcessRunner()
    pr.register_executable("apt-get")
    fs = InMemoryFileSystem()
    fs.add_dir(_LISTS)
    fresh = _LISTS / "deb_InRelease"
    fs.add_file(fresh, content="")
    fs.set_mtime(fresh, _NOW - timedelta(hours=1))

    engine = _engine(fs, pr, _clock_at(_NOW))
    engine.add(
        AptUpdateStateChanger(
            AptUpdateParameters(),
            process_runner=pr,
            file_system=fs,
            env=ScriptedEnv.linux(),
            clock=_clock_at(_NOW),
        )
    )
    result = engine.start(max_workers=1)

    assert pr.calls == []
    assert result.reports[0].outcome is NodeOutcome.SKIPPED_ALREADY_APPLIED


def test_engine_halts_on_invalid_assessment() -> None:
    # apt-get missing from PATH → INVALID
    pr = ScriptedProcessRunner()
    fs = InMemoryFileSystem()
    fs.add_dir(_LISTS)

    engine = _engine(fs, pr, _clock_at(_NOW))
    engine.add(
        AptUpdateStateChanger(
            AptUpdateParameters(),
            process_runner=pr,
            file_system=fs,
            env=ScriptedEnv.linux(),
            clock=_clock_at(_NOW),
        )
    )
    result = engine.start(max_workers=1)

    assert pr.calls == []
    assert result.reports[0].outcome is NodeOutcome.FAILED_INVALID


def test_engine_runs_then_post_assess_finds_fresh_lists() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(_LISTS)
    # Stale Release file → READY.
    rel = _LISTS / "deb_InRelease"
    fs.add_file(rel, content="")
    fs.set_mtime(rel, _NOW - timedelta(days=3))

    # The fake process runner won't touch the FS, so we simulate apt-get
    # update's side effect by bumping the mtime via a wrapping runner.
    bumping = _MtimeBumpingRunner(fs, rel, _NOW)
    bumping.register_executable("apt-get")
    bumping.register(
        ("apt-get", "update"),
        ProcessResult(exit_code=0, stdout="", stderr="", duration_ms=42),
    )

    engine = _engine(fs, bumping, _clock_at(_NOW))
    engine.add(
        AptUpdateStateChanger(
            AptUpdateParameters(),
            process_runner=bumping,
            file_system=fs,
            env=ScriptedEnv.linux(),
            clock=_clock_at(_NOW),
        )
    )
    result = engine.start(max_workers=1)

    assert len(bumping.calls) == 1
    assert result.reports[0].outcome is NodeOutcome.SUCCESS
