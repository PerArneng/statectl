from __future__ import annotations

from statectl._interfaces.fs import FsIoError
from statectl._interfaces.process import ProcessLaunchError, ProcessTimeout
from statectl._state_changer import ExistingState
from tests.fakes.failing_file_system import FailingFileSystem
from tests.fakes.failing_process_runner import FailingProcessRunner
from tests.statechangers._launchd_helpers import (
    PLIST_CONTENT,
    USER_PLIST_PATH,
    make_rig,
)


def test_process_timeout_during_loaded_probe_becomes_invalid() -> None:
    rig = make_rig()
    rig.fs.add_file(USER_PLIST_PATH, content=PLIST_CONTENT)
    pr = FailingProcessRunner(rig.pr)
    pr.fail("run", ProcessTimeout("too long"))

    changer = rig.changer()
    # swap in the failing wrapper
    assessment = type(changer)(
        changer.params,
        file_system=rig.fs,
        process_runner=pr,
        env=rig.env,
    ).assess_state()

    assert assessment.state is ExistingState.INVALID
    assert any("launchctl probe timed out" in i for i in assessment.issues)


def test_process_launch_error_during_loaded_probe_becomes_invalid() -> None:
    rig = make_rig()
    rig.fs.add_file(USER_PLIST_PATH, content=PLIST_CONTENT)
    pr = FailingProcessRunner(rig.pr)
    pr.fail("run", ProcessLaunchError("os boom"))

    changer = rig.changer()
    assessment = type(changer)(
        changer.params,
        file_system=rig.fs,
        process_runner=pr,
        env=rig.env,
    ).assess_state()

    assert assessment.state is ExistingState.INVALID
    assert any("launchctl probe launch error" in i for i in assessment.issues)


def test_fs_error_reading_existing_plist_becomes_invalid() -> None:
    rig = make_rig()
    rig.fs.add_file(USER_PLIST_PATH, content=PLIST_CONTENT)
    fs = FailingFileSystem(rig.fs)
    fs.fail("read_text_file", FsIoError("io boom", path=USER_PLIST_PATH))

    changer = rig.changer()
    assessment = type(changer)(
        changer.params,
        file_system=fs,
        process_runner=rig.pr,
        env=rig.env,
    ).assess_state()

    assert assessment.state is ExistingState.INVALID
    assert any("cannot read existing plist" in i for i in assessment.issues)
