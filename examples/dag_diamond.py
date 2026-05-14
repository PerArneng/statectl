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
    NewTextFileParameters,
    NewTextFileStateChanger,
)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)

        def file_changer(name: str) -> NewTextFileStateChanger:
            return NewTextFileStateChanger(
                NewTextFileParameters(path=root / f"{name}.txt", text=f"{name}\n")
            )

        # Diamond:
        #     a
        #    / \
        #   b   c
        #    \ /
        #     d
        a = ExecutionNode(file_changer("a"))
        b = ExecutionNode(file_changer("b"), depends_on=[a])
        c = ExecutionNode(file_changer("c"), depends_on=[a])
        d = ExecutionNode(file_changer("d"), depends_on=[b, c])

        engine = StateCtlEngine.create_engine()
        for node in (a, b, c, d):
            engine.add(node)

        result = engine.start(max_workers=4)
        print(f"\nengine ok = {result.ok}")
        for report in result.reports:
            print(f"  {report.node_name}: {report.outcome.value}")


if __name__ == "__main__":
    main()
