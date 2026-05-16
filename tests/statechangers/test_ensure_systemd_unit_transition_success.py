from __future__ import annotations

from statectl._interfaces.process import ProcessResult
from statectl._state_changer import ResultStatus
from tests.statechangers._systemd_helpers import (
    DEFAULT_UNIT,
    USER_UNIT_DIR,
    make_changer,
    make_fs_with_user_unit_dir,
    make_pr_with_systemctl,
    make_unit_content,
)


def test_transition_writes_unit_reloads_enables_and_starts() -> None:
    fs = make_fs_with_user_unit_dir()
    pr = make_pr_with_systemctl()

    result = make_changer(fs=fs, pr=pr).transition()

    assert result.status is ResultStatus.SUCCESS
    unit_path = USER_UNIT_DIR / DEFAULT_UNIT
    assert fs.is_file(unit_path)
    assert fs.read_text_file(unit_path) == make_unit_content()

    verbs = [c.argv[2] for c in pr.calls if c.argv[:2] == ("systemctl", "--user")]
    # daemon-reload comes after write, then enable, then start (unit was absent
    # so reload-or-restart is not used).
    assert verbs == ["daemon-reload", "enable", "start"]


def test_transition_disables_and_stops_when_flags_false() -> None:
    fs = make_fs_with_user_unit_dir()
    pr = make_pr_with_systemctl()

    result = make_changer(
        fs=fs,
        pr=pr,
        enabled=False,
        started=False,
    ).transition()

    assert result.status is ResultStatus.SUCCESS
    verbs = [c.argv[2] for c in pr.calls if c.argv[:2] == ("systemctl", "--user")]
    assert verbs == ["daemon-reload", "disable", "stop"]


def test_transition_reload_or_restart_when_content_changed_and_flag_set() -> None:
    fs = make_fs_with_user_unit_dir()
    # Pre-existing unit with different content → content_changed=True.
    drifted = make_unit_content().replace("/usr/bin/true", "/usr/bin/false")
    fs.add_file(USER_UNIT_DIR / DEFAULT_UNIT, content=drifted)
    pr = make_pr_with_systemctl()

    result = make_changer(fs=fs, pr=pr, reload_on_change=True).transition()
    assert result.status is ResultStatus.SUCCESS
    verbs = [c.argv[2] for c in pr.calls if c.argv[:2] == ("systemctl", "--user")]
    assert verbs == ["daemon-reload", "enable", "reload-or-restart"]


def test_transition_plain_start_when_content_changed_but_reload_flag_off() -> None:
    fs = make_fs_with_user_unit_dir()
    drifted = make_unit_content().replace("/usr/bin/true", "/usr/bin/false")
    fs.add_file(USER_UNIT_DIR / DEFAULT_UNIT, content=drifted)
    pr = make_pr_with_systemctl()

    result = make_changer(fs=fs, pr=pr, reload_on_change=False).transition()
    assert result.status is ResultStatus.SUCCESS
    verbs = [c.argv[2] for c in pr.calls if c.argv[:2] == ("systemctl", "--user")]
    assert verbs == ["daemon-reload", "enable", "start"]


def test_transition_system_scope_does_not_pass_user_flag() -> None:
    from pathlib import Path
    from tests.fakes.in_memory_file_system import InMemoryFileSystem

    fs = InMemoryFileSystem()
    fs.add_dir(Path("/etc"))
    fs.add_dir(Path("/etc/systemd"))
    fs.add_dir(Path("/etc/systemd/system"))
    pr = make_pr_with_systemctl()

    result = make_changer(fs=fs, pr=pr, scope="system").transition()
    assert result.status is ResultStatus.SUCCESS
    for c in pr.calls:
        assert "--user" not in c.argv
    verbs = [c.argv[1] for c in pr.calls]
    assert verbs == ["daemon-reload", "enable", "start"]
