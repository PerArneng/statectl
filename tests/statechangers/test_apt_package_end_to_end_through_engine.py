from __future__ import annotations

from pathlib import Path
from typing import Mapping, Sequence, override

from statectl import StateCtl
from statectl._engine_result import NodeOutcome
from statectl._interfaces.process import ProcessResult
from statectl._modules import DefaultLogger, InMemoryVariableRegistry
from statectl._statechangers import (
    AptPackageParameters,
    AptPackageStateChanger,
)
from tests.fakes.in_memory_file_system import InMemoryFileSystem
from tests.fakes.scripted_env import ScriptedEnv
from tests.fakes.scripted_http_client import ScriptedHttpClient
from tests.fakes.scripted_process_runner import ScriptedProcessRunner


class _StatefulAptRunner(ScriptedProcessRunner):
    """ScriptedProcessRunner that flips an internal "installed" / "held" set
    on `apt-get install` / `apt-get remove` / `apt-mark hold`, so subsequent
    `dpkg -s` calls reflect the new state. Exercises the engine's
    post-assess after a successful transition.
    """

    def __init__(self) -> None:
        super().__init__()
        self._installed: set[str] = set()
        self._held: set[str] = set()
        for binary in (
            "apt-get",
            "dpkg",
            "apt-mark",
            "apt-cache",
            "dpkg-query",
        ):
            self.register_executable(binary)

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
        argv_tuple = tuple(argv)
        if argv_tuple[:3] == ("apt-get", "-y", "install"):
            target = argv_tuple[3].split("=", 1)[0]
            self._installed.add(target)
            super().run(argv, cwd=cwd, env=env, stdin=stdin, timeout=timeout)
            return ProcessResult(exit_code=0, stdout="ok", stderr="", duration_ms=0)
        if argv_tuple[:3] == ("apt-get", "-y", "remove"):
            self._installed.discard(argv_tuple[3])
            self._held.discard(argv_tuple[3])
            super().run(argv, cwd=cwd, env=env, stdin=stdin, timeout=timeout)
            return ProcessResult(exit_code=0, stdout="ok", stderr="", duration_ms=0)
        if argv_tuple[:2] == ("apt-mark", "hold"):
            self._held.add(argv_tuple[2])
            super().run(argv, cwd=cwd, env=env, stdin=stdin, timeout=timeout)
            return ProcessResult(exit_code=0, stdout="", stderr="", duration_ms=0)
        if argv_tuple[:2] == ("apt-mark", "showhold"):
            super().run(argv, cwd=cwd, env=env, stdin=stdin, timeout=timeout)
            return ProcessResult(
                exit_code=0,
                stdout="\n".join(sorted(self._held)),
                stderr="",
                duration_ms=0,
            )
        if argv_tuple[:2] == ("dpkg", "-s"):
            name = argv_tuple[2]
            super().run(argv, cwd=cwd, env=env, stdin=stdin, timeout=timeout)
            return ProcessResult(
                exit_code=0 if name in self._installed else 1,
                stdout="",
                stderr="",
                duration_ms=0,
            )
        return super().run(argv, cwd=cwd, env=env, stdin=stdin, timeout=timeout)


def _fs() -> InMemoryFileSystem:
    fs = InMemoryFileSystem()
    fs.add_file(Path("/etc/debian_version"), content="12.0\n")
    return fs


def _engine(fs: InMemoryFileSystem, pr: ScriptedProcessRunner) -> StateCtl:
    return StateCtl(
        logger=DefaultLogger("test"),
        file_system=fs,
        process_runner=pr,
        http_client=ScriptedHttpClient(),
        env=ScriptedEnv.linux(),
        variable_registry=InMemoryVariableRegistry(),
    )


def test_engine_installs_and_post_assess_succeeds() -> None:
    fs = _fs()
    pr = _StatefulAptRunner()
    changer = AptPackageStateChanger(
        AptPackageParameters(name="curl"),
        file_system=fs,
        process_runner=pr,
    )

    engine = _engine(fs, pr)
    engine.add(changer)
    result = engine.start(max_workers=1)

    assert result.ok, result.reports[0].result
    assert result.reports[0].outcome is NodeOutcome.SUCCESS


def test_engine_skips_when_already_installed() -> None:
    fs = _fs()
    pr = _StatefulAptRunner()
    pr._installed.add("curl")  # noqa: SLF001 (test boundary)

    changer = AptPackageStateChanger(
        AptPackageParameters(name="curl"),
        file_system=fs,
        process_runner=pr,
    )

    engine = _engine(fs, pr)
    engine.add(changer)
    result = engine.start(max_workers=1)

    assert result.ok
    assert result.reports[0].outcome is NodeOutcome.SKIPPED_ALREADY_APPLIED


def test_engine_halts_on_invalid_name() -> None:
    fs = _fs()
    pr = _StatefulAptRunner()
    changer = AptPackageStateChanger(
        AptPackageParameters(name="bad name"),
        file_system=fs,
        process_runner=pr,
    )

    engine = _engine(fs, pr)
    engine.add(changer)
    result = engine.start(max_workers=1)

    assert not result.ok
    assert result.reports[0].outcome is NodeOutcome.FAILED_INVALID


def test_engine_halts_on_apt_install_failure() -> None:
    fs = _fs()
    pr = ScriptedProcessRunner()
    for b in ("apt-get", "dpkg", "apt-mark", "apt-cache", "dpkg-query"):
        pr.register_executable(b)
    pr.register(
        ("dpkg", "-s", "curl"),
        ProcessResult(exit_code=1, stdout="", stderr="", duration_ms=0),
    )
    pr.register(
        ("apt-mark", "showhold"),
        ProcessResult(exit_code=0, stdout="", stderr="", duration_ms=0),
    )
    pr.register(
        ("apt-get", "-y", "install", "curl"),
        ProcessResult(exit_code=1, stdout="", stderr="boom", duration_ms=0),
    )
    changer = AptPackageStateChanger(
        AptPackageParameters(name="curl"),
        file_system=fs,
        process_runner=pr,
    )

    engine = _engine(fs, pr)
    engine.add(changer)
    result = engine.start(max_workers=1)

    assert not result.ok
    assert result.reports[0].outcome is NodeOutcome.FAILED_TRANSITION
    report = result.reports[0].result
    assert report is not None
    assert report.code == "APT_INSTALL_FAILED"
