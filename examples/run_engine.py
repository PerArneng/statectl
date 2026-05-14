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

from statectl.execution_node import ExecutionNode
from statectl.state_ctl_engine import StateCtlEngine
from statectl.statechangers.new_text_file import (
    NewTextFileParameters,
    NewTextFileStateChanger,
)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp) / "hello.txt"
        changer = NewTextFileStateChanger(
            NewTextFileParameters(path=target, text="hello from statectl\n")
        )

        engine = StateCtlEngine.create_engine()
        engine.add(ExecutionNode(changer))
        engine.start()

        print(f"--- contents of {target} ---")
        print(target.read_text())


if __name__ == "__main__":
    main()
