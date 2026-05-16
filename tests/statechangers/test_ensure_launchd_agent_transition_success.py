from __future__ import annotations

from statectl._interfaces.process import ProcessResult
from statectl._state_changer import ResultStatus
from tests.statechangers._launchd_helpers import (
    DEFAULT_DOMAIN,
    DEFAULT_LABEL,
    USER_AGENTS_DIR,
    make_changer,
    make_fs_with_user_agents_dir,
    make_plist,
    make_pr_with_launchctl,
)


def test_transition_writes_plist_and_bootstraps() -> None:
    fs = make_fs_with_user_agents_dir()
    pr = make_pr_with_launchctl()
    pr.register(
        ("launchctl", "bootstrap"),
        ProcessResult(exit_code=0, stdout="", stderr="", duration_ms=12),
    )

    result = make_changer(fs=fs, pr=pr).transition()

    assert result.status is ResultStatus.SUCCESS
    plist_path = USER_AGENTS_DIR / f"{DEFAULT_LABEL}.plist"
    assert fs.is_file(plist_path)
    assert fs.read_text_file(plist_path) == make_plist(DEFAULT_LABEL)

    bootstrap_calls = [c for c in pr.calls if c.argv[:2] == ("launchctl", "bootstrap")]
    assert len(bootstrap_calls) == 1
    assert bootstrap_calls[0].argv == (
        "launchctl",
        "bootstrap",
        DEFAULT_DOMAIN,
        str(plist_path),
    )


def test_transition_writes_plist_only_when_loaded_false() -> None:
    fs = make_fs_with_user_agents_dir()
    pr = make_pr_with_launchctl()

    result = make_changer(fs=fs, pr=pr, loaded=False).transition()

    assert result.status is ResultStatus.SUCCESS
    plist_path = USER_AGENTS_DIR / f"{DEFAULT_LABEL}.plist"
    assert fs.is_file(plist_path)
    # No bootstrap call at all.
    assert not any(c.argv[:2] == ("launchctl", "bootstrap") for c in pr.calls)


def test_transition_falls_back_to_legacy_load_when_bootstrap_fails() -> None:
    fs = make_fs_with_user_agents_dir()
    pr = make_pr_with_launchctl()
    pr.register(
        ("launchctl", "bootstrap"),
        ProcessResult(exit_code=1, stdout="", stderr="unsupported", duration_ms=5),
    )
    pr.register(
        ("launchctl", "load"),
        ProcessResult(exit_code=0, stdout="", stderr="", duration_ms=8),
    )

    result = make_changer(fs=fs, pr=pr).transition()
    assert result.status is ResultStatus.SUCCESS
    assert "legacy launchctl load" in result.message


def test_transition_details_include_duration_and_exit_code() -> None:
    fs = make_fs_with_user_agents_dir()
    pr = make_pr_with_launchctl()
    pr.register(
        ("launchctl", "bootstrap"),
        ProcessResult(exit_code=0, stdout="ok", stderr="", duration_ms=42),
    )
    result = make_changer(fs=fs, pr=pr).transition()
    assert result.details["exit_code"] == "0"
    assert result.details["duration_ms"] == "42"
