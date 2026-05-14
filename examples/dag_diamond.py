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
        a = file_changer("a")
        b = file_changer("b")
        c = file_changer("c")
        d = file_changer("d")

        engine = StateCtlEngine.create_engine()
        engine.add(a)
        engine.add(b, depends_on=[a])
        engine.add(c, depends_on=[a])
        engine.add(d, depends_on=[b, c])

        result = engine.start(max_workers=4)
        print(f"\nengine ok = {result.ok}")
        for report in result.reports:
            print(f"  {report.node_name}: {report.outcome.value}")


if __name__ == "__main__":
    main()
