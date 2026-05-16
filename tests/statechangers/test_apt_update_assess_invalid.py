from __future__ import annotations

from pathlib import Path

from statectl._state_changer import ExistingState
from statectl._statechangers import AptUpdateParameters, AptUpdateStateChanger
from tests.fakes.in_memory_file_system import InMemoryFileSystem
from tests.fakes.scripted_clock import ScriptedClock
from tests.fakes.scripted_env import ScriptedEnv
from tests.fakes.scripted_process_runner import ScriptedProcessRunner


def _build(
    *,
    platform_linux: bool = True,
    apt_on_path: bool = True,
    lists_dir_present: bool = True,
    lists_dir_is_file: bool = False,
) -> AptUpdateStateChanger:
    pr = ScriptedProcessRunner()
    if apt_on_path:
        pr.register_executable("apt-get")
    fs = InMemoryFileSystem()
    lists_dir = Path("/var/lib/apt/lists")
    if lists_dir_present:
        if lists_dir_is_file:
            fs.add_dir(lists_dir.parent)
            fs.add_file(lists_dir, content="")
        else:
            fs.add_dir(lists_dir)
    env = ScriptedEnv.linux() if platform_linux else ScriptedEnv.darwin()
    return AptUpdateStateChanger(
        AptUpdateParameters(),
        process_runner=pr,
        file_system=fs,
        env=env,
        clock=ScriptedClock(),
    )


def test_invalid_when_platform_is_not_linux() -> None:
    changer = _build(platform_linux=False)
    a = changer.assess_state()
    assert a.state is ExistingState.INVALID
    assert any("not Debian-family" in i for i in a.issues)


def test_invalid_when_apt_get_missing() -> None:
    changer = _build(apt_on_path=False)
    a = changer.assess_state()
    assert a.state is ExistingState.INVALID
    assert any("apt-get not on PATH" in i for i in a.issues)


def test_invalid_when_lists_dir_missing() -> None:
    changer = _build(lists_dir_present=False)
    a = changer.assess_state()
    assert a.state is ExistingState.INVALID
    assert any("apt lists directory missing" in i for i in a.issues)


def test_invalid_when_lists_path_is_not_a_directory() -> None:
    changer = _build(lists_dir_is_file=True)
    a = changer.assess_state()
    assert a.state is ExistingState.INVALID
    assert any("not a directory" in i for i in a.issues)


def test_invalid_collects_all_issues_in_one_pass() -> None:
    changer = _build(platform_linux=False, apt_on_path=False, lists_dir_present=False)
    a = changer.assess_state()
    assert a.state is ExistingState.INVALID
    joined = " ".join(a.issues)
    assert "not Debian-family" in joined
    assert "apt-get not on PATH" in joined
    assert "apt lists directory missing" in joined
