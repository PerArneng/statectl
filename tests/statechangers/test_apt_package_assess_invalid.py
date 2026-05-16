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


_DEBIAN_MARKER = Path("/etc/debian_version")


def _fs_with_debian_marker() -> InMemoryFileSystem:
    fs = InMemoryFileSystem()
    fs.add_file(_DEBIAN_MARKER, content="12.0\n")
    return fs


def _register_all(pr: ScriptedProcessRunner) -> None:
    for binary in ("apt-get", "dpkg", "apt-mark", "apt-cache", "dpkg-query"):
        pr.register_executable(binary)


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


def test_invalid_when_not_debian_platform() -> None:
    fs = InMemoryFileSystem()  # no debian marker
    pr = ScriptedProcessRunner()
    _register_all(pr)

    assess = _changer(fs, pr).assess_state()

    assert assess.state is ExistingState.INVALID
    assert any("Debian-family" in i for i in assess.issues)


def test_invalid_when_apt_binaries_missing() -> None:
    fs = _fs_with_debian_marker()
    pr = ScriptedProcessRunner()  # no binaries

    assess = _changer(fs, pr).assess_state()

    assert assess.state is ExistingState.INVALID
    joined = "\n".join(assess.issues)
    assert "apt-get binary not on PATH" in joined
    assert "dpkg binary not on PATH" in joined
    assert "apt-mark binary not on PATH" in joined


def test_invalid_when_name_has_shell_metacharacters() -> None:
    fs = _fs_with_debian_marker()
    pr = ScriptedProcessRunner()
    _register_all(pr)

    assess = _changer(fs, pr, name="curl; rm -rf /").assess_state()

    assert assess.state is ExistingState.INVALID
    assert any("invalid package name" in i for i in assess.issues)


def test_invalid_collects_all_input_issues_in_one_pass() -> None:
    fs = InMemoryFileSystem()  # not debian
    pr = ScriptedProcessRunner()  # no binaries

    assess = _changer(fs, pr, name="bad name").assess_state()

    assert assess.state is ExistingState.INVALID
    joined = "\n".join(assess.issues)
    assert "Debian-family" in joined
    assert "apt-get binary not on PATH" in joined
    assert "invalid package name" in joined


def test_invalid_when_installed_higher_version_and_no_allow_downgrade() -> None:
    fs = _fs_with_debian_marker()
    pr = ScriptedProcessRunner()
    _register_all(pr)
    # Installed
    pr.register(
        ("dpkg", "-s", "curl"),
        ProcessResult(exit_code=0, stdout="Status: install ok installed", stderr="", duration_ms=0),
    )
    # Installed version 8.0
    pr.register(
        ("dpkg-query", "-W", "-f=${Version}", "curl"),
        ProcessResult(exit_code=0, stdout="8.0.0-1", stderr="", duration_ms=0),
    )
    # 8.0.0-1 gt 7.0.0-1 → exit 0
    pr.register(
        ("dpkg", "--compare-versions", "8.0.0-1", "gt", "7.0.0-1"),
        ProcessResult(exit_code=0, stdout="", stderr="", duration_ms=0),
    )
    # apt-cache madison shows version available
    pr.register(
        ("apt-cache", "madison", "curl"),
        ProcessResult(
            exit_code=0,
            stdout="     curl |    7.0.0-1 | http://deb.debian.org/debian bookworm/main amd64 Packages\n",
            stderr="",
            duration_ms=0,
        ),
    )

    assess = _changer(fs, pr, version="7.0.0-1").assess_state()

    assert assess.state is ExistingState.INVALID
    assert any("would require downgrade" in i for i in assess.issues)


def test_invalid_when_version_not_in_apt_cache() -> None:
    fs = _fs_with_debian_marker()
    pr = ScriptedProcessRunner()
    _register_all(pr)
    pr.register(
        ("dpkg", "-s", "curl"),
        ProcessResult(exit_code=1, stdout="", stderr="", duration_ms=0),
    )
    pr.register(
        ("apt-cache", "madison", "curl"),
        ProcessResult(
            exit_code=0,
            stdout="     curl |    7.0.0-1 | http://deb.debian.org/debian bookworm/main amd64 Packages\n",
            stderr="",
            duration_ms=0,
        ),
    )

    assess = _changer(fs, pr, version="9.9.9").assess_state()

    assert assess.state is ExistingState.INVALID
    assert any("not found in apt cache" in i for i in assess.issues)
