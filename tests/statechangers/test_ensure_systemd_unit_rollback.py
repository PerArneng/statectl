from __future__ import annotations

from statectl._interfaces.process import ProcessResult
from statectl._state_changer import ExistingState, ResultStatus
from statectl._statechangers import (
    EnsureSystemdUnitParameters,
    EnsureSystemdUnitRollbackStateChanger,
)
from tests.fakes.scripted_process_runner import ScriptedProcessRunner
from tests.statechangers._systemd_helpers import (
    DEFAULT_UNIT,
    USER_UNIT_DIR,
    make_changer,
    make_env_linux,
    make_fs_with_user_unit_dir,
    make_pr_with_systemctl,
    make_unit_content,
)


def _rollback_from(c) -> EnsureSystemdUnitRollbackStateChanger:  # type: ignore[no-untyped-def]
    rb = c.rollback()
    assert isinstance(rb, EnsureSystemdUnitRollbackStateChanger)
    return rb


def test_rollback_already_applied_when_unit_absent_and_inactive() -> None:
    pr = make_pr_with_systemctl()
    pr.register(
        ("systemctl", "--user", "is-active"),
        ProcessResult(exit_code=0, stdout="inactive", stderr="", duration_ms=0),
    )
    rb = EnsureSystemdUnitRollbackStateChanger(
        EnsureSystemdUnitParameters(
            unit_name=DEFAULT_UNIT,
            unit_content=make_unit_content(),
            scope="user",
        ),
        file_system=make_fs_with_user_unit_dir(),
        process_runner=pr,
        env=make_env_linux(),
    )
    assert rb.assess_state().state is ExistingState.ALREADY_APPLIED


def test_rollback_ready_when_unit_exists_with_matching_content() -> None:
    fs = make_fs_with_user_unit_dir()
    fs.add_file(USER_UNIT_DIR / DEFAULT_UNIT, content=make_unit_content())
    rb = _rollback_from(make_changer(fs=fs))
    assert rb.assess_state().state is ExistingState.READY


def test_rollback_invalid_when_unit_content_differs() -> None:
    fs = make_fs_with_user_unit_dir()
    fs.add_file(
        USER_UNIT_DIR / DEFAULT_UNIT,
        content=make_unit_content().replace("/usr/bin/true", "/usr/bin/other"),
    )
    rb = _rollback_from(make_changer(fs=fs))
    assessment = rb.assess_state()
    assert assessment.state is ExistingState.INVALID
    assert any("differs from what we wrote" in i for i in assessment.issues)


def test_rollback_invalid_when_systemctl_missing() -> None:
    fs = make_fs_with_user_unit_dir()
    fs.add_file(USER_UNIT_DIR / DEFAULT_UNIT, content=make_unit_content())
    rb = _rollback_from(make_changer(fs=fs, pr=ScriptedProcessRunner()))
    assessment = rb.assess_state()
    assert assessment.state is ExistingState.INVALID
    assert any("systemctl not on PATH" in i for i in assessment.issues)


def test_rollback_transition_stops_disables_unlinks_and_reloads() -> None:
    fs = make_fs_with_user_unit_dir()
    unit_path = USER_UNIT_DIR / DEFAULT_UNIT
    fs.add_file(unit_path, content=make_unit_content())

    pr = make_pr_with_systemctl()
    rb = _rollback_from(make_changer(fs=fs, pr=pr))
    result = rb.transition()

    assert result.status is ResultStatus.SUCCESS
    assert not fs.exists(unit_path)
    verbs = [c.argv[2] for c in pr.calls if c.argv[:2] == ("systemctl", "--user")]
    assert verbs == ["stop", "disable", "daemon-reload"]


def test_rollback_skips_when_unit_already_gone() -> None:
    fs = make_fs_with_user_unit_dir()
    pr = make_pr_with_systemctl()
    rb = _rollback_from(make_changer(fs=fs, pr=pr))
    result = rb.transition()
    assert result.status is ResultStatus.SKIPPED


def test_rollback_invalid_when_unit_path_is_a_directory() -> None:
    fs = make_fs_with_user_unit_dir()
    fs.add_dir(USER_UNIT_DIR / DEFAULT_UNIT)
    rb = _rollback_from(make_changer(fs=fs))
    assessment = rb.assess_state()
    assert assessment.state is ExistingState.INVALID
    assert any("not a regular file" in i for i in assessment.issues)
