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
        marker = Path(tmp) / "marker"

        print("--- first run: marker does not exist, command should run ---")
        ctl1 = StateCtl.new()
        ctl1.add(ctl1.changers().run(["touch", str(marker)], creates=marker))
        ctl1.start()
        assert marker.exists(), "expected touch to create the marker"

        print("\n--- second run: marker exists, command should be skipped ---")
        ctl2 = StateCtl.new()
        ctl2.add(ctl2.changers().run(["touch", str(marker)], creates=marker))
        ctl2.start()


if __name__ == "__main__":
    main()
