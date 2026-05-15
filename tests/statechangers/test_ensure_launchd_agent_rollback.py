from __future__ import annotations

from statectl._interfaces.process import ProcessResult
from statectl._state_changer import ExistingState, ResultStatus
from tests.statechangers._launchd_helpers import (
    OTHER_PLIST_CONTENT,
    PLIST_CONTENT,
    USER_PLIST_PATH,
    make_rig,
    script_exit,
    script_loaded,
)


def test_rollback_already_applied_when_plist_absent_and_not_loaded() -> None:
    rig = make_rig()
    script_loaded(rig.pr, loaded=False)

    assessment = rig.rollback().assess_state()
    assert assessment.state is ExistingState.ALREADY_APPLIED


def test_rollback_ready_when_plist_present() -> None:
    rig = make_rig()
    rig.fs.add_file(USER_PLIST_PATH, content=PLIST_CONTENT)
    script_loaded(rig.pr, loaded=False)

    assessment = rig.rollback().assess_state()
    assert assessment.state is ExistingState.READY


def test_rollback_invalid_when_plist_content_differs() -> None:
    rig = make_rig()
    rig.fs.add_file(USER_PLIST_PATH, content=OTHER_PLIST_CONTENT)
    script_loaded(rig.pr, loaded=False)

    assessment = rig.rollback().assess_state()
    assert assessment.state is ExistingState.INVALID
    assert any("differs from what we wrote" in i for i in assessment.issues)


def test_rollback_transition_unloads_and_removes() -> None:
    rig = make_rig()
    rig.fs.add_file(USER_PLIST_PATH, content=PLIST_CONTENT)
    script_loaded(rig.pr, loaded=True)
    script_exit(rig.pr, ("launchctl", "unload"), 0)

    result = rig.rollback().transition()

    assert result.status is ResultStatus.SUCCESS
    assert not rig.fs.exists(USER_PLIST_PATH)
    assert any(c.argv[:2] == ("launchctl", "unload") for c in rig.pr.calls)


def test_rollback_transition_uses_bootout_with_domain_target() -> None:
    rig = make_rig()
    rig.fs.add_file(USER_PLIST_PATH, content=PLIST_CONTENT)
    script_loaded(rig.pr, loaded=True)
    script_exit(rig.pr, ("launchctl", "bootout"), 0)

    result = rig.rollback(domain_target="gui/501").transition()

    assert result.status is ResultStatus.SUCCESS
    assert any(
        c.argv == ("launchctl", "bootout", "gui/501/com.example.foo")
        for c in rig.pr.calls
    )


def test_rollback_transition_skips_unload_when_not_loaded() -> None:
    rig = make_rig()
    rig.fs.add_file(USER_PLIST_PATH, content=PLIST_CONTENT)
    script_loaded(rig.pr, loaded=False)

    result = rig.rollback().transition()
    assert result.status is ResultStatus.SUCCESS
    assert not any(c.argv[:2] == ("launchctl", "unload") for c in rig.pr.calls)
    assert not rig.fs.exists(USER_PLIST_PATH)


def test_rollback_transition_failure_on_unload_nonzero() -> None:
    rig = make_rig()
    rig.fs.add_file(USER_PLIST_PATH, content=PLIST_CONTENT)
    script_loaded(rig.pr, loaded=True)
    rig.pr.register(
        ("launchctl", "unload"),
        ProcessResult(exit_code=3, stdout="", stderr="boom", duration_ms=1),
    )

    result = rig.rollback().transition()
    assert result.status is ResultStatus.FAILURE
    assert result.code == "LAUNCHCTL_UNLOAD_FAILED"
    # plist still in place since unload failed
    assert rig.fs.exists(USER_PLIST_PATH)
