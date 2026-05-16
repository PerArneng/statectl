from __future__ import annotations

from statectl._interfaces.process import ProcessResult
from statectl._state_changer import ExistingState, ResultStatus
from statectl._statechangers import (
    EnsureLaunchdAgentParameters,
    EnsureLaunchdAgentRollbackStateChanger,
)
from tests.statechangers._launchd_helpers import (
    DEFAULT_DOMAIN,
    DEFAULT_LABEL,
    USER_AGENTS_DIR,
    make_changer,
    make_env_darwin,
    make_fs_with_user_agents_dir,
    make_plist,
    make_pr_with_launchctl,
)


def _rollback_from(c) -> EnsureLaunchdAgentRollbackStateChanger:  # type: ignore[no-untyped-def]
    rb = c.rollback()
    assert isinstance(rb, EnsureLaunchdAgentRollbackStateChanger)
    return rb


def test_rollback_already_applied_when_plist_absent_and_not_loaded() -> None:
    rb = _rollback_from(make_changer())
    pr = make_pr_with_launchctl()
    pr.register(
        ("launchctl", "print"),
        ProcessResult(exit_code=1, stdout="", stderr="", duration_ms=0),
    )
    rb_with_pr = EnsureLaunchdAgentRollbackStateChanger(
        EnsureLaunchdAgentParameters(
            label=DEFAULT_LABEL,
            plist_content=make_plist(),
            scope="user",
            loaded=True,
            domain_target=DEFAULT_DOMAIN,
        ),
        file_system=make_fs_with_user_agents_dir(),
        process_runner=pr,
        env=make_env_darwin(),
    )
    assert rb_with_pr.assess_state().state is ExistingState.ALREADY_APPLIED
    _ = rb


def test_rollback_ready_when_plist_exists_with_matching_content() -> None:
    fs = make_fs_with_user_agents_dir()
    fs.add_file(
        USER_AGENTS_DIR / f"{DEFAULT_LABEL}.plist",
        content=make_plist(DEFAULT_LABEL),
    )
    rb = _rollback_from(make_changer(fs=fs))
    assert rb.assess_state().state is ExistingState.READY


def test_rollback_invalid_when_plist_content_differs() -> None:
    fs = make_fs_with_user_agents_dir()
    fs.add_file(
        USER_AGENTS_DIR / f"{DEFAULT_LABEL}.plist",
        content=make_plist(DEFAULT_LABEL).replace("/usr/bin/true", "/usr/bin/other"),
    )
    rb = _rollback_from(make_changer(fs=fs))
    assessment = rb.assess_state()
    assert assessment.state is ExistingState.INVALID
    assert any("differs from what we wrote" in i for i in assessment.issues)


def test_rollback_transition_boots_out_and_unlinks_plist() -> None:
    fs = make_fs_with_user_agents_dir()
    plist_path = USER_AGENTS_DIR / f"{DEFAULT_LABEL}.plist"
    fs.add_file(plist_path, content=make_plist(DEFAULT_LABEL))

    pr = make_pr_with_launchctl()
    pr.register(
        ("launchctl", "bootout"),
        ProcessResult(exit_code=0, stdout="", stderr="", duration_ms=2),
    )

    rb = _rollback_from(make_changer(fs=fs, pr=pr))
    result = rb.transition()
    assert result.status is ResultStatus.SUCCESS
    assert not fs.exists(plist_path)
    bootout_calls = [c for c in pr.calls if c.argv[:2] == ("launchctl", "bootout")]
    assert bootout_calls and bootout_calls[0].argv == (
        "launchctl",
        "bootout",
        f"{DEFAULT_DOMAIN}/{DEFAULT_LABEL}",
    )


def test_rollback_skips_when_plist_already_gone() -> None:
    fs = make_fs_with_user_agents_dir()
    pr = make_pr_with_launchctl()
    pr.register(
        ("launchctl", "bootout"),
        ProcessResult(exit_code=0, stdout="", stderr="", duration_ms=0),
    )
    rb = _rollback_from(make_changer(fs=fs, pr=pr))
    result = rb.transition()
    assert result.status is ResultStatus.SKIPPED


def test_rollback_invalid_when_launchctl_missing() -> None:
    fs = make_fs_with_user_agents_dir()
    fs.add_file(
        USER_AGENTS_DIR / f"{DEFAULT_LABEL}.plist",
        content=make_plist(DEFAULT_LABEL),
    )
    from tests.fakes.scripted_process_runner import ScriptedProcessRunner
    rb = _rollback_from(make_changer(fs=fs, pr=ScriptedProcessRunner()))
    assessment = rb.assess_state()
    assert assessment.state is ExistingState.INVALID
    assert any("launchctl not on PATH" in i for i in assessment.issues)


def test_rollback_falls_back_to_legacy_unload() -> None:
    fs = make_fs_with_user_agents_dir()
    plist_path = USER_AGENTS_DIR / f"{DEFAULT_LABEL}.plist"
    fs.add_file(plist_path, content=make_plist(DEFAULT_LABEL))

    pr = make_pr_with_launchctl()
    pr.register(
        ("launchctl", "bootout"),
        ProcessResult(exit_code=1, stdout="", stderr="unsupported", duration_ms=1),
    )
    pr.register(
        ("launchctl", "unload"),
        ProcessResult(exit_code=0, stdout="", stderr="", duration_ms=1),
    )
    rb = _rollback_from(make_changer(fs=fs, pr=pr))
    result = rb.transition()
    assert result.status is ResultStatus.SUCCESS
    assert not fs.exists(plist_path)
