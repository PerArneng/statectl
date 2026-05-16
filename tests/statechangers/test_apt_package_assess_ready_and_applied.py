from __future__ import annotations

from pathlib import Path

from statectl._interfaces.process import ProcessResult
from statectl._state_changer import ExistingState
from statectl._statechangers import (
    AptPackageParameters,
    AptPackageStateChanger,
)
from tests.fakes.in_memory_file_system import InMemoryFileSystem
from tests.fakes.scripted_process_runner import ScriptedProcessRunner


def _rig() -> tuple[InMemoryFileSystem, ScriptedProcessRunner]:
    fs = InMemoryFileSystem()
    fs.add_file(Path("/etc/debian_version"), content="12.0\n")
    pr = ScriptedProcessRunner()
    for binary in ("apt-get", "dpkg", "apt-mark", "apt-cache", "dpkg-query"):
        pr.register_executable(binary)
    return fs, pr


def _installed(pr: ScriptedProcessRunner, name: str, yes: bool) -> None:
    pr.register(
        ("dpkg", "-s", name),
        ProcessResult(
            exit_code=0 if yes else 1, stdout="", stderr="", duration_ms=0
        ),
    )


def _installed_version(
    pr: ScriptedProcessRunner, name: str, version: str
) -> None:
    pr.register(
        ("dpkg-query", "-W", "-f=${Version}", name),
        ProcessResult(exit_code=0, stdout=version, stderr="", duration_ms=0),
    )


def _madison(pr: ScriptedProcessRunner, name: str, version: str) -> None:
    pr.register(
        ("apt-cache", "madison", name),
        ProcessResult(
            exit_code=0,
            stdout=f"     {name} |    {version} | http://example.com main\n",
            stderr="",
            duration_ms=0,
        ),
    )


def _showhold(pr: ScriptedProcessRunner, held: list[str]) -> None:
    pr.register(
        ("apt-mark", "showhold"),
        ProcessResult(
            exit_code=0,
            stdout="\n".join(held) + ("\n" if held else ""),
            stderr="",
            duration_ms=0,
        ),
    )


def _changer(
    fs: InMemoryFileSystem,
    pr: ScriptedProcessRunner,
    *,
    name: str = "curl",
    version: str | None = None,
    hold: bool = False,
    allow_downgrade: bool = False,
) -> AptPackageStateChanger:
    return AptPackageStateChanger(
        AptPackageParameters(
            name=name, version=version, hold=hold, allow_downgrade=allow_downgrade
        ),
        file_system=fs,
        process_runner=pr,
    )


def test_ready_when_not_installed() -> None:
    fs, pr = _rig()
    _installed(pr, "curl", False)
    _showhold(pr, [])

    assert _changer(fs, pr).assess_state().state is ExistingState.READY


def test_already_applied_when_installed_no_version_no_hold() -> None:
    fs, pr = _rig()
    _installed(pr, "curl", True)
    _showhold(pr, [])

    assert (
        _changer(fs, pr).assess_state().state is ExistingState.ALREADY_APPLIED
    )


def test_already_applied_when_installed_version_matches() -> None:
    fs, pr = _rig()
    _installed(pr, "curl", True)
    _installed_version(pr, "curl", "7.88.1")
    _madison(pr, "curl", "7.88.1")
    _showhold(pr, [])

    assess = _changer(fs, pr, version="7.88.1").assess_state()

    assert assess.state is ExistingState.ALREADY_APPLIED


def test_ready_when_installed_version_differs_and_allow_downgrade() -> None:
    fs, pr = _rig()
    _installed(pr, "curl", True)
    _installed_version(pr, "curl", "8.0.0-1")
    # allow_downgrade=True skips the gt comparison branch
    _madison(pr, "curl", "7.0.0-1")
    _showhold(pr, [])

    assess = _changer(
        fs, pr, version="7.0.0-1", allow_downgrade=True
    ).assess_state()

    assert assess.state is ExistingState.READY


def test_ready_when_installed_lower_version_and_no_allow_downgrade() -> None:
    fs, pr = _rig()
    _installed(pr, "curl", True)
    _installed_version(pr, "curl", "7.0.0-1")
    pr.register(
        ("dpkg", "--compare-versions", "7.0.0-1", "gt", "8.0.0-1"),
        ProcessResult(exit_code=1, stdout="", stderr="", duration_ms=0),
    )
    _madison(pr, "curl", "8.0.0-1")
    _showhold(pr, [])

    assess = _changer(fs, pr, version="8.0.0-1").assess_state()

    assert assess.state is ExistingState.READY


def test_already_applied_when_installed_and_held() -> None:
    fs, pr = _rig()
    _installed(pr, "curl", True)
    _showhold(pr, ["curl", "wget"])

    assess = _changer(fs, pr, hold=True).assess_state()

    assert assess.state is ExistingState.ALREADY_APPLIED


def test_ready_when_installed_but_not_held_and_hold_requested() -> None:
    fs, pr = _rig()
    _installed(pr, "curl", True)
    _showhold(pr, ["wget"])

    assess = _changer(fs, pr, hold=True).assess_state()

    assert assess.state is ExistingState.READY
