from __future__ import annotations

from pathlib import Path
from typing import Mapping, Sequence, override

from statectl import StateCtl
from statectl._engine_result import NodeOutcome
from statectl._interfaces.process import ProcessResult
from statectl._modules import DefaultLogger, InMemoryVariableRegistry, RealHashing
from statectl._statechangers import (
    AptRepositoryParameters,
    AptRepositoryStateChanger,
    InlineKey,
)
from tests.fakes.in_memory_file_system import InMemoryFileSystem
from tests.fakes.scripted_archive import ScriptedArchive
from tests.fakes.scripted_clock import ScriptedClock
from tests.fakes.scripted_env import ScriptedEnv
from tests.fakes.scripted_http_client import ScriptedHttpClient
from tests.fakes.scripted_process_runner import ScriptedProcessRunner


FP = "ABCDEF1234567890ABCDEF1234567890ABCDEF12"

EXPECTED_SOURCES = (
    "deb [signed-by=/etc/apt/keyrings/docker.gpg] "
    "https://download.docker.com/linux/ubuntu jammy stable\n"
)


class _DearmorMaterialisingPR(ScriptedProcessRunner):
    def __init__(self, fs: InMemoryFileSystem) -> None:
        super().__init__()
        self._fs = fs

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
        result = super().run(argv, cwd=cwd, env=env, stdin=stdin, timeout=timeout)
        argv_tuple = tuple(argv)
        if (
            len(argv_tuple) >= 4
            and argv_tuple[0] == "gpg"
            and argv_tuple[1] == "--dearmor"
            and argv_tuple[2] == "-o"
            and result.exit_code == 0
        ):
            self._fs.add_file(Path(argv_tuple[3]), content="binary")
        return result


def _ok_fs() -> InMemoryFileSystem:
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/etc"))
    fs.add_dir(Path("/etc/apt"))
    fs.add_dir(Path("/etc/apt/sources.list.d"))
    fs.add_dir(Path("/etc/apt/keyrings"))
    return fs


def _pr(fs: InMemoryFileSystem) -> _DearmorMaterialisingPR:
    pr = _DearmorMaterialisingPR(fs)
    pr.register_executable("gpg")
    pr.register(
        ("gpg", "--show-keys", "--with-colons"),
        ProcessResult(
            exit_code=0, stdout=f"fpr:::::::::{FP}:\n", stderr="", duration_ms=1
        ),
    )
    pr.register(
        ("gpg", "--dearmor"),
        ProcessResult(exit_code=0, stdout="", stderr="", duration_ms=1),
    )
    return pr


def _engine(
    fs: InMemoryFileSystem,
    pr: ScriptedProcessRunner,
    http: ScriptedHttpClient,
    env: ScriptedEnv,
) -> StateCtl:
    return StateCtl(
        logger=DefaultLogger("test"),
        file_system=fs,
        process_runner=pr,
        http_client=http,
        env=env,
        archive=ScriptedArchive(),
        hashing=RealHashing(),
        clock=ScriptedClock(),
        variable_registry=InMemoryVariableRegistry(),
    )


def _changer(
    fs: InMemoryFileSystem,
    pr: ScriptedProcessRunner,
    http: ScriptedHttpClient,
    env: ScriptedEnv,
) -> AptRepositoryStateChanger:
    return AptRepositoryStateChanger(
        AptRepositoryParameters(
            name="docker",
            uri="https://download.docker.com/linux/ubuntu",
            suite="jammy",
            components=("stable",),
            signing_key=InlineKey(armored="X", fingerprint=FP),
        ),
        file_system=fs,
        process_runner=pr,
        http_client=http,
        env=env,
    )


def test_engine_runs_transition_and_succeeds() -> None:
    fs = _ok_fs()
    pr = _pr(fs)
    http = ScriptedHttpClient()
    env = ScriptedEnv.linux()
    engine = _engine(fs, pr, http, env)
    engine.add(_changer(fs, pr, http, env))

    result = engine.start(max_workers=1)

    assert result.ok, result.reports[0].result
    assert result.reports[0].outcome is NodeOutcome.SUCCESS
    assert fs.exists(Path("/etc/apt/sources.list.d/docker.list"))


def test_engine_skips_when_already_applied() -> None:
    fs = _ok_fs()
    fs.add_file(
        Path("/etc/apt/sources.list.d/docker.list"), content=EXPECTED_SOURCES
    )
    fs.add_file(Path("/etc/apt/keyrings/docker.gpg"), content="binary")
    pr = _pr(fs)
    http = ScriptedHttpClient()
    env = ScriptedEnv.linux()
    engine = _engine(fs, pr, http, env)
    engine.add(_changer(fs, pr, http, env))

    result = engine.start(max_workers=1)

    assert result.ok
    assert result.reports[0].outcome is NodeOutcome.SKIPPED_ALREADY_APPLIED


def test_engine_halts_on_invalid_when_not_linux() -> None:
    fs = _ok_fs()
    pr = _pr(fs)
    http = ScriptedHttpClient()
    env = ScriptedEnv.darwin()
    engine = _engine(fs, pr, http, env)
    engine.add(_changer(fs, pr, http, env))

    result = engine.start(max_workers=1)

    assert not result.ok
    assert result.reports[0].outcome is NodeOutcome.FAILED_INVALID
