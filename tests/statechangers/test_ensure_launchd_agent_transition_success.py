from __future__ import annotations

from pathlib import Path

from statectl._interfaces.process import ProcessResult
from statectl._state_changer import ResultStatus
from tests.statechangers._launchd_helpers import (
    LABEL,
    PLIST_CONTENT,
    SYSTEM_PLIST_PATH,
    USER_PLIST_PATH,
    make_rig,
    script_exit,
    script_loaded,
)


def test_transition_writes_plist_and_loads_legacy() -> None:
    rig = make_rig()
    # `launchctl load -w` and the loaded probe both return 0
    script_loaded(rig.pr, loaded=True)
    script_exit(rig.pr, ("launchctl", "load"), 0)

    result = rig.changer().transition()

    assert result.status is ResultStatus.SUCCESS
    assert rig.fs.exists(USER_PLIST_PATH)
    assert rig.fs.read_text_file(USER_PLIST_PATH) == PLIST_CONTENT
    assert any(
        c.argv[:2] == ("launchctl", "load") and "-w" in c.argv
        for c in rig.pr.calls
    )


def test_transition_uses_bootstrap_when_domain_target_provided() -> None:
    rig = make_rig()
    script_loaded(rig.pr, loaded=True)
    script_exit(rig.pr, ("launchctl", "bootstrap"), 0)

    result = rig.changer(domain_target="gui/501").transition()

    assert result.status is ResultStatus.SUCCESS
    assert any(
        c.argv == (
            "launchctl",
            "bootstrap",
            "gui/501",
            str(USER_PLIST_PATH),
        )
        for c in rig.pr.calls
    )


def test_transition_writes_only_when_loaded_false() -> None:
    rig = make_rig()
    # loaded=False → no launchctl load call at all
    result = rig.changer(loaded=False).transition()

    assert result.status is ResultStatus.SUCCESS
    assert rig.fs.exists(USER_PLIST_PATH)
    assert not any(c.argv[:2] == ("launchctl", "load") for c in rig.pr.calls)
    assert not any(c.argv[:2] == ("launchctl", "bootstrap") for c in rig.pr.calls)


def test_transition_overwrites_drifted_owned_plist() -> None:
    rig = make_rig()
    drifted = PLIST_CONTENT.replace("<dict>", "<dict>\n    <!-- drift -->")
    rig.fs.add_file(USER_PLIST_PATH, content=drifted)
    script_exit(rig.pr, ("launchctl", "load"), 0)

    result = rig.changer().transition()

    assert result.status is ResultStatus.SUCCESS
    assert rig.fs.read_text_file(USER_PLIST_PATH) == PLIST_CONTENT


def test_transition_writes_to_system_path_for_system_scope() -> None:
    rig = make_rig(create_system_dir=True)
    script_exit(rig.pr, ("launchctl", "load"), 0)

    result = rig.changer(scope="system", loaded=False).transition()

    assert result.status is ResultStatus.SUCCESS
    assert rig.fs.exists(SYSTEM_PLIST_PATH)


def test_transition_attaches_load_details() -> None:
    rig = make_rig()
    rig.pr.register(
        ("launchctl", "load"),
        ProcessResult(exit_code=0, stdout="ok-out", stderr="warn", duration_ms=42),
    )

    result = rig.changer().transition()

    assert result.status is ResultStatus.SUCCESS
    assert result.details["exit_code"] == "0"
    assert result.details["stdout"] == "ok-out"
    assert result.details["stderr"] == "warn"
    assert result.details["duration_ms"] == "42"


def test_transition_failure_when_launchctl_returns_nonzero() -> None:
    rig = make_rig()
    rig.pr.register(
        ("launchctl", "load"),
        ProcessResult(exit_code=2, stdout="", stderr="bad plist", duration_ms=1),
    )

    result = rig.changer().transition()

    assert result.status is ResultStatus.FAILURE
    assert result.code == "LAUNCHCTL_LOAD_FAILED"
    assert "exited 2" in result.message


def test_transition_failure_when_plist_vanishes_before_load() -> None:
    """If the plist write silently fails to persist, the vanish guard fires
    before launchctl load is invoked."""
    from typing import override

    from tests.fakes.in_memory_file_system import InMemoryFileSystem

    class _NoopWriteFs(InMemoryFileSystem):
        @override
        def write_text_file(
            self, path: Path, text: str, encoding: str = "utf-8"
        ) -> None:
            return None  # pretend to write but don't store anything

    fs = _NoopWriteFs()
    fs.add_dir(Path("/Users/test"))
    fs.add_dir(Path("/Users/test/Library"))
    fs.add_dir(Path("/Users/test/Library/LaunchAgents"))
    rig = make_rig()
    changer = type(rig.changer())(
        rig.changer().params,
        file_system=fs,
        process_runner=rig.pr,
        env=rig.env,
    )

    result = changer.transition()
    assert result.status is ResultStatus.FAILURE
    assert result.code == "PLIST_VANISHED"
    assert LABEL in changer.name()
