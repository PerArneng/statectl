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

from statectl import StateCtl


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp) / "hello.txt"

        ctl = StateCtl.new()
        sc = ctl.changers()

        ctl.add(sc.new_file(target, "hello from statectl\n"))
        ctl.start()

        print(f"--- contents of {target} ---")
        print(target.read_text())


if __name__ == "__main__":
    main()
