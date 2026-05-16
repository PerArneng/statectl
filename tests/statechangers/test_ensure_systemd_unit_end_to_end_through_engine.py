from __future__ import annotations

from statectl import StateCtl
from statectl._engine_result import NodeOutcome
from statectl._interfaces.process import ProcessResult
from statectl._modules import DefaultLogger, InMemoryVariableRegistry, RealHashing
from statectl._statechangers import (
    EnsureSystemdUnitParameters,
    EnsureSystemdUnitStateChanger,
)
from tests.fakes.in_memory_file_system import InMemoryFileSystem
from tests.fakes.scripted_archive import ScriptedArchive
from tests.fakes.scripted_clock import ScriptedClock
from tests.fakes.scripted_env import ScriptedEnv
from tests.fakes.scripted_http_client import ScriptedHttpClient
from tests.fakes.scripted_process_runner import ScriptedProcessRunner
from tests.statechangers._systemd_helpers import (
    DEFAULT_UNIT,
    HOME,
    USER_UNIT_DIR,
    make_fs_with_user_unit_dir,
    make_unit_content,
)


def _engine(
    fs: InMemoryFileSystem, pr: ScriptedProcessRunner, *, linux: bool = True
) -> StateCtl:
    env = ScriptedEnv.linux(home=HOME) if linux else ScriptedEnv.darwin(home=HOME)
    return StateCtl(
        logger=DefaultLogger("test"),
        file_system=fs,
        process_runner=pr,
        http_client=ScriptedHttpClient(),
        env=env,
        archive=ScriptedArchive(),
        hashing=RealHashing(),
        clock=ScriptedClock(),
        variable_registry=InMemoryVariableRegistry(),
    )


def _make_changer(
    fs: InMemoryFileSystem, pr: ScriptedProcessRunner
) -> EnsureSystemdUnitStateChanger:
    return EnsureSystemdUnitStateChanger(
        EnsureSystemdUnitParameters(
            unit_name=DEFAULT_UNIT,
            unit_content=make_unit_content(),
            scope="user",
        ),
        file_system=fs,
        process_runner=pr,
        env=ScriptedEnv.linux(home=HOME),
    )


def test_engine_runs_transition_when_ready() -> None:
    fs = make_fs_with_user_unit_dir()
    pr = ScriptedProcessRunner()
    pr.register_executable("systemctl")
    # Post-transition the engine re-assesses and expects ALREADY_APPLIED, so
    # is-enabled / is-active must report the desired runtime state.
    pr.register(
        ("systemctl", "--user", "is-enabled"),
        ProcessResult(exit_code=0, stdout="enabled", stderr="", duration_ms=0),
    )
    pr.register(
        ("systemctl", "--user", "is-active"),
        ProcessResult(exit_code=0, stdout="active", stderr="", duration_ms=0),
    )
    changer = _make_changer(fs, pr)

    engine = _engine(fs, pr)
    engine.add(changer)
    result = engine.start(max_workers=1)

    assert result.ok
    assert result.reports[0].outcome is NodeOutcome.SUCCESS
    assert fs.is_file(USER_UNIT_DIR / DEFAULT_UNIT)


def test_engine_skips_when_already_applied() -> None:
    fs = make_fs_with_user_unit_dir()
    fs.add_file(USER_UNIT_DIR / DEFAULT_UNIT, content=make_unit_content())
    pr = ScriptedProcessRunner()
    pr.register_executable("systemctl")
    pr.register(
        ("systemctl", "--user", "is-enabled"),
        ProcessResult(exit_code=0, stdout="enabled", stderr="", duration_ms=0),
    )
    pr.register(
        ("systemctl", "--user", "is-active"),
        ProcessResult(exit_code=0, stdout="active", stderr="", duration_ms=0),
    )
    changer = _make_changer(fs, pr)

    engine = _engine(fs, pr)
    engine.add(changer)
    result = engine.start(max_workers=1)
    assert result.ok
    assert result.reports[0].outcome is NodeOutcome.SKIPPED_ALREADY_APPLIED


def test_engine_halts_on_invalid_when_platform_not_linux() -> None:
    fs = make_fs_with_user_unit_dir()
    pr = ScriptedProcessRunner()
    pr.register_executable("systemctl")
    changer = EnsureSystemdUnitStateChanger(
        EnsureSystemdUnitParameters(
            unit_name=DEFAULT_UNIT,
            unit_content=make_unit_content(),
            scope="user",
        ),
        file_system=fs,
        process_runner=pr,
        env=ScriptedEnv.darwin(home=HOME),
    )

    engine = _engine(fs, pr, linux=False)
    engine.add(changer)
    result = engine.start(max_workers=1)
    assert not result.ok
    assert result.reports[0].outcome is NodeOutcome.FAILED_INVALID
