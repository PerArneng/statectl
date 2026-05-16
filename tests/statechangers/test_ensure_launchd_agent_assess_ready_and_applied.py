from __future__ import annotations

from statectl._interfaces.process import ProcessResult
from statectl._state_changer import ExistingState
from tests.statechangers._launchd_helpers import (
    DEFAULT_DOMAIN,
    DEFAULT_LABEL,
    SYSTEM_DAEMONS_DIR,
    USER_AGENTS_DIR,
    make_changer,
    make_fs_with_system_daemons_dir,
    make_fs_with_user_agents_dir,
    make_plist,
    make_pr_with_launchctl,
)


def _launchctl_print_loaded(pr_loaded: bool) -> ProcessResult:
    return ProcessResult(
        exit_code=0 if pr_loaded else 1,
        stdout="",
        stderr="",
        duration_ms=0,
    )


def test_ready_when_plist_absent() -> None:
    assessment = make_changer().assess_state()
    assert assessment.state is ExistingState.READY


def test_ready_when_plist_present_with_matching_label_but_drift_content() -> None:
    # Same Label, but the file body on disk doesn't match the desired content.
    # This is OUR plist that drifted — READY to overwrite.
    fs = make_fs_with_user_agents_dir()
    drifted = make_plist(DEFAULT_LABEL).replace("/usr/bin/true", "/usr/bin/false")
    fs.add_file(USER_AGENTS_DIR / f"{DEFAULT_LABEL}.plist", content=drifted)

    pr = make_pr_with_launchctl()
    pr.register(("launchctl", "print"), _launchctl_print_loaded(True))

    assessment = make_changer(fs=fs, pr=pr).assess_state()
    assert assessment.state is ExistingState.READY


def test_already_applied_when_plist_matches_and_loaded_false() -> None:
    fs = make_fs_with_user_agents_dir()
    fs.add_file(
        USER_AGENTS_DIR / f"{DEFAULT_LABEL}.plist",
        content=make_plist(DEFAULT_LABEL),
    )
    assessment = make_changer(fs=fs, loaded=False).assess_state()
    assert assessment.state is ExistingState.ALREADY_APPLIED


def test_already_applied_when_plist_matches_and_launchctl_print_succeeds() -> None:
    fs = make_fs_with_user_agents_dir()
    fs.add_file(
        USER_AGENTS_DIR / f"{DEFAULT_LABEL}.plist",
        content=make_plist(DEFAULT_LABEL),
    )
    pr = make_pr_with_launchctl()
    pr.register(("launchctl", "print"), _launchctl_print_loaded(True))

    assessment = make_changer(fs=fs, pr=pr).assess_state()
    assert assessment.state is ExistingState.ALREADY_APPLIED


def test_ready_when_plist_matches_but_not_loaded() -> None:
    fs = make_fs_with_user_agents_dir()
    fs.add_file(
        USER_AGENTS_DIR / f"{DEFAULT_LABEL}.plist",
        content=make_plist(DEFAULT_LABEL),
    )
    pr = make_pr_with_launchctl()
    pr.register(
        ("launchctl", "print"),
        ProcessResult(exit_code=1, stdout="", stderr="service not loaded", duration_ms=0),
    )

    assessment = make_changer(fs=fs, pr=pr).assess_state()
    assert assessment.state is ExistingState.READY


def test_already_applied_system_scope_with_default_domain_target() -> None:
    fs = make_fs_with_system_daemons_dir()
    fs.add_file(
        SYSTEM_DAEMONS_DIR / f"{DEFAULT_LABEL}.plist",
        content=make_plist(DEFAULT_LABEL),
    )
    pr = make_pr_with_launchctl()
    pr.register(("launchctl", "print"), _launchctl_print_loaded(True))

    assessment = make_changer(
        fs=fs,
        pr=pr,
        scope="system",
        domain_target=None,
    ).assess_state()
    assert assessment.state is ExistingState.ALREADY_APPLIED


def test_loaded_true_explicit_domain_target_used_in_service_check() -> None:
    # Verify that the service target uses params.domain_target/label.
    fs = make_fs_with_user_agents_dir()
    fs.add_file(
        USER_AGENTS_DIR / f"{DEFAULT_LABEL}.plist",
        content=make_plist(DEFAULT_LABEL),
    )
    pr = make_pr_with_launchctl()
    pr.register(("launchctl", "print"), _launchctl_print_loaded(True))

    assessment = make_changer(fs=fs, pr=pr, domain_target=DEFAULT_DOMAIN).assess_state()
    assert assessment.state is ExistingState.ALREADY_APPLIED
    # And the launchctl print call had the gui/501/<label> argument.
    print_calls = [c for c in pr.calls if c.argv[:2] == ("launchctl", "print")]
    assert print_calls and print_calls[-1].argv[2] == f"{DEFAULT_DOMAIN}/{DEFAULT_LABEL}"
