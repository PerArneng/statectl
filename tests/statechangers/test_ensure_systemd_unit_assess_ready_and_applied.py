from __future__ import annotations

from statectl._interfaces.process import ProcessResult
from statectl._state_changer import ExistingState
from tests.statechangers._systemd_helpers import (
    DEFAULT_UNIT,
    SYSTEM_UNIT_DIR,
    USER_UNIT_DIR,
    make_changer,
    make_fs_with_system_unit_dir,
    make_fs_with_user_unit_dir,
    make_pr_with_systemctl,
    make_unit_content,
)


def _pr_with(is_enabled: str, is_active: str) -> object:
    pr = make_pr_with_systemctl()
    pr.register(
        ("systemctl", "--user", "is-enabled"),
        ProcessResult(exit_code=0, stdout=is_enabled, stderr="", duration_ms=0),
    )
    pr.register(
        ("systemctl", "--user", "is-active"),
        ProcessResult(exit_code=0, stdout=is_active, stderr="", duration_ms=0),
    )
    return pr


def test_ready_when_unit_absent() -> None:
    assessment = make_changer().assess_state()
    assert assessment.state is ExistingState.READY


def test_already_applied_when_unit_matches_enabled_and_active() -> None:
    fs = make_fs_with_user_unit_dir()
    fs.add_file(USER_UNIT_DIR / DEFAULT_UNIT, content=make_unit_content())
    pr = _pr_with(is_enabled="enabled", is_active="active")
    assessment = make_changer(fs=fs, pr=pr).assess_state()  # type: ignore[arg-type]
    assert assessment.state is ExistingState.ALREADY_APPLIED


def test_ready_when_unit_matches_but_disabled_and_we_want_enabled() -> None:
    fs = make_fs_with_user_unit_dir()
    fs.add_file(USER_UNIT_DIR / DEFAULT_UNIT, content=make_unit_content())
    pr = _pr_with(is_enabled="disabled", is_active="active")
    assessment = make_changer(fs=fs, pr=pr).assess_state()  # type: ignore[arg-type]
    assert assessment.state is ExistingState.READY


def test_ready_when_unit_matches_but_inactive_and_we_want_started() -> None:
    fs = make_fs_with_user_unit_dir()
    fs.add_file(USER_UNIT_DIR / DEFAULT_UNIT, content=make_unit_content())
    pr = _pr_with(is_enabled="enabled", is_active="inactive")
    assessment = make_changer(fs=fs, pr=pr).assess_state()  # type: ignore[arg-type]
    assert assessment.state is ExistingState.READY


def test_already_applied_when_started_false_and_unit_inactive() -> None:
    fs = make_fs_with_user_unit_dir()
    fs.add_file(USER_UNIT_DIR / DEFAULT_UNIT, content=make_unit_content())
    pr = _pr_with(is_enabled="disabled", is_active="inactive")
    assessment = make_changer(
        fs=fs,
        pr=pr,  # type: ignore[arg-type]
        enabled=False,
        started=False,
    ).assess_state()
    assert assessment.state is ExistingState.ALREADY_APPLIED


def test_already_applied_treats_static_as_acceptable_when_disabled_wanted() -> None:
    fs = make_fs_with_user_unit_dir()
    fs.add_file(USER_UNIT_DIR / DEFAULT_UNIT, content=make_unit_content())
    pr = _pr_with(is_enabled="static", is_active="inactive")
    assessment = make_changer(
        fs=fs,
        pr=pr,  # type: ignore[arg-type]
        enabled=False,
        started=False,
    ).assess_state()
    assert assessment.state is ExistingState.ALREADY_APPLIED


def test_ready_when_content_drifted_even_if_runtime_matches() -> None:
    fs = make_fs_with_user_unit_dir()
    drifted = make_unit_content().replace("/usr/bin/true", "/usr/bin/false")
    fs.add_file(USER_UNIT_DIR / DEFAULT_UNIT, content=drifted)
    pr = _pr_with(is_enabled="enabled", is_active="active")
    assessment = make_changer(fs=fs, pr=pr).assess_state()  # type: ignore[arg-type]
    assert assessment.state is ExistingState.READY


def test_system_scope_already_applied() -> None:
    fs = make_fs_with_system_unit_dir()
    fs.add_file(SYSTEM_UNIT_DIR / DEFAULT_UNIT, content=make_unit_content())
    pr = make_pr_with_systemctl()
    pr.register(
        ("systemctl", "is-enabled"),
        ProcessResult(exit_code=0, stdout="enabled", stderr="", duration_ms=0),
    )
    pr.register(
        ("systemctl", "is-active"),
        ProcessResult(exit_code=0, stdout="active", stderr="", duration_ms=0),
    )
    assessment = make_changer(fs=fs, pr=pr, scope="system").assess_state()
    assert assessment.state is ExistingState.ALREADY_APPLIED
    # User-scope flag should not appear.
    assert not any(
        c.argv[:2] == ("systemctl", "--user")
        for c in pr.calls
    )


def test_query_reads_stderr_when_stdout_empty() -> None:
    # Real systemctl sometimes writes the state to stderr (older versions).
    fs = make_fs_with_user_unit_dir()
    fs.add_file(USER_UNIT_DIR / DEFAULT_UNIT, content=make_unit_content())
    pr = make_pr_with_systemctl()
    pr.register(
        ("systemctl", "--user", "is-enabled"),
        ProcessResult(exit_code=0, stdout="", stderr="enabled", duration_ms=0),
    )
    pr.register(
        ("systemctl", "--user", "is-active"),
        ProcessResult(exit_code=0, stdout="", stderr="active", duration_ms=0),
    )
    assessment = make_changer(fs=fs, pr=pr).assess_state()
    assert assessment.state is ExistingState.ALREADY_APPLIED
