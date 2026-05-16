from __future__ import annotations

from statectl import StateCtl
from statectl._engine_result import NodeOutcome
from statectl._interfaces.process import ProcessResult
from statectl._modules import DefaultLogger, InMemoryVariableRegistry, RealHashing
from statectl._statechangers import (
    EnsureLaunchdAgentParameters,
    EnsureLaunchdAgentStateChanger,
)
from tests.fakes.in_memory_file_system import InMemoryFileSystem
from tests.fakes.scripted_archive import ScriptedArchive
from tests.fakes.scripted_clock import ScriptedClock
from tests.fakes.scripted_env import ScriptedEnv
from tests.fakes.scripted_http_client import ScriptedHttpClient
from tests.fakes.scripted_process_runner import ScriptedProcessRunner
from tests.statechangers._launchd_helpers import (
    DEFAULT_DOMAIN,
    DEFAULT_LABEL,
    HOME,
    USER_AGENTS_DIR,
    make_plist,
)


def _engine(fs: InMemoryFileSystem, pr: ScriptedProcessRunner) -> StateCtl:
    return StateCtl(
        logger=DefaultLogger("test"),
        file_system=fs,
        process_runner=pr,
        http_client=ScriptedHttpClient(),
        env=ScriptedEnv.darwin(home=HOME),
        archive=ScriptedArchive(),
        hashing=RealHashing(),
        clock=ScriptedClock(),
        variable_registry=InMemoryVariableRegistry(),
    )


def _make() -> EnsureLaunchdAgentStateChanger:
    fs = InMemoryFileSystem()
    fs.add_dir(HOME)
    fs.add_dir(HOME / "Library")
    fs.add_dir(USER_AGENTS_DIR)
    pr = ScriptedProcessRunner()
    pr.register_executable("launchctl")
    pr.register(
        ("launchctl", "bootstrap"),
        ProcessResult(exit_code=0, stdout="", stderr="", duration_ms=0),
    )
    return EnsureLaunchdAgentStateChanger(
        EnsureLaunchdAgentParameters(
            label=DEFAULT_LABEL,
            plist_content=make_plist(),
            scope="user",
            loaded=True,
            domain_target=DEFAULT_DOMAIN,
        ),
        file_system=fs,
        process_runner=pr,
        env=ScriptedEnv.darwin(home=HOME),
    )


def test_engine_runs_transition_when_ready() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(HOME)
    fs.add_dir(HOME / "Library")
    fs.add_dir(USER_AGENTS_DIR)

    pr = ScriptedProcessRunner()
    pr.register_executable("launchctl")
    pr.register(
        ("launchctl", "bootstrap"),
        ProcessResult(exit_code=0, stdout="", stderr="", duration_ms=0),
    )
    pr.register(
        ("launchctl", "print"),
        ProcessResult(exit_code=0, stdout="", stderr="", duration_ms=0),
    )

    changer = EnsureLaunchdAgentStateChanger(
        EnsureLaunchdAgentParameters(
            label=DEFAULT_LABEL,
            plist_content=make_plist(),
            scope="user",
            loaded=True,
            domain_target=DEFAULT_DOMAIN,
        ),
        file_system=fs,
        process_runner=pr,
        env=ScriptedEnv.darwin(home=HOME),
    )

    engine = _engine(fs, pr)
    engine.add(changer)
    result = engine.start(max_workers=1)
    assert result.ok
    assert result.reports[0].outcome is NodeOutcome.SUCCESS
    assert fs.is_file(USER_AGENTS_DIR / f"{DEFAULT_LABEL}.plist")


def test_engine_skips_when_already_applied() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(HOME)
    fs.add_dir(HOME / "Library")
    fs.add_dir(USER_AGENTS_DIR)
    fs.add_file(USER_AGENTS_DIR / f"{DEFAULT_LABEL}.plist", content=make_plist())

    pr = ScriptedProcessRunner()
    pr.register_executable("launchctl")
    pr.register(
        ("launchctl", "print"),
        ProcessResult(exit_code=0, stdout="", stderr="", duration_ms=0),
    )

    changer = EnsureLaunchdAgentStateChanger(
        EnsureLaunchdAgentParameters(
            label=DEFAULT_LABEL,
            plist_content=make_plist(),
            scope="user",
            loaded=True,
            domain_target=DEFAULT_DOMAIN,
        ),
        file_system=fs,
        process_runner=pr,
        env=ScriptedEnv.darwin(home=HOME),
    )
    engine = _engine(fs, pr)
    engine.add(changer)
    result = engine.start(max_workers=1)
    assert result.ok
    assert result.reports[0].outcome is NodeOutcome.SKIPPED_ALREADY_APPLIED


def test_engine_halts_on_invalid_when_platform_not_darwin() -> None:
    fs = InMemoryFileSystem()
    fs.add_dir(HOME)
    fs.add_dir(HOME / "Library")
    fs.add_dir(USER_AGENTS_DIR)
    pr = ScriptedProcessRunner()
    pr.register_executable("launchctl")

    changer = EnsureLaunchdAgentStateChanger(
        EnsureLaunchdAgentParameters(
            label=DEFAULT_LABEL,
            plist_content=make_plist(),
            scope="user",
            loaded=True,
            domain_target=DEFAULT_DOMAIN,
        ),
        file_system=fs,
        process_runner=pr,
        env=ScriptedEnv.linux(home=HOME),
    )

    engine = StateCtl(
        logger=DefaultLogger("test"),
        file_system=fs,
        process_runner=pr,
        http_client=ScriptedHttpClient(),
        env=ScriptedEnv.linux(home=HOME),
        archive=ScriptedArchive(),
        hashing=RealHashing(),
        clock=ScriptedClock(),
        variable_registry=InMemoryVariableRegistry(),
    )
    engine.add(changer)
    result = engine.start(max_workers=1)
    assert not result.ok
    assert result.reports[0].outcome is NodeOutcome.FAILED_INVALID
