from __future__ import annotations

from pathlib import Path

from statectl._statechangers import (
    EnsureHomebrewInstalledParameters,
    EnsureHomebrewInstalledStateChanger,
)
from tests.fakes.failing_http_client import FailingHttpClient
from tests.fakes.failing_process_runner import FailingProcessRunner
from tests.fakes.in_memory_file_system import InMemoryFileSystem
from tests.fakes.scripted_env import ScriptedEnv
from tests.fakes.scripted_http_client import ScriptedHttpClient
from tests.fakes.scripted_process_runner import ScriptedProcessRunner


def test_assess_does_not_call_raising_action_methods_on_capabilities() -> None:
    """assess_state must use only non-raising query methods. We wire the
    failing fakes to raise on every action method; assess must still not
    raise.
    """
    fs = InMemoryFileSystem()
    fs.add_dir(Path("/opt"))
    http = FailingHttpClient(ScriptedHttpClient())
    http.fail("get", RuntimeError("should not be called"))
    http.fail("download_to_file", RuntimeError("should not be called"))
    pr = FailingProcessRunner(ScriptedProcessRunner())
    pr.fail("run", RuntimeError("should not be called"))

    changer = EnsureHomebrewInstalledStateChanger(
        EnsureHomebrewInstalledParameters(
            brew_prefix=Path("/opt/homebrew"),
            accept_eula=True,
        ),
        file_system=fs,
        process_runner=pr,
        http_client=http,
        env=ScriptedEnv.darwin(),
    )

    changer.assess_state()  # must not raise
