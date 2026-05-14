#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = ["statectl"]
#
# [tool.uv.sources]
# statectl = { path = "../", editable = true }
# ///
import logging
import tempfile
from pathlib import Path

from statectl import ExecutionNode
from statectl import StateCtlEngine
from statectl.statechangers import (
    RunCommandParameters,
    RunCommandStateChanger,
)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    with tempfile.TemporaryDirectory() as tmp:
        marker = Path(tmp) / "marker"

        def make_changer() -> RunCommandStateChanger:
            return RunCommandStateChanger(
                RunCommandParameters(
                    argv=("touch", str(marker)),
                    creates=marker,
                )
            )

        print("--- first run: marker does not exist, command should run ---")
        engine1 = StateCtlEngine.create_engine()
        engine1.add(ExecutionNode(make_changer()))
        engine1.start()
        assert marker.exists(), "expected touch to create the marker"

        print("\n--- second run: marker exists, command should be skipped ---")
        engine2 = StateCtlEngine.create_engine()
        engine2.add(ExecutionNode(make_changer()))
        engine2.start()


if __name__ == "__main__":
    main()
