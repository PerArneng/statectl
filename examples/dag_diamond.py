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
        root = Path(tmp)

        ctl = StateCtl.new()
        sc = ctl.changers()

        # Diamond:
        #     a
        #    / \
        #   b   c
        #    \ /
        #     d
        a = sc.new_file(root / "a.txt", "a\n")
        b = sc.new_file(root / "b.txt", "b\n")
        c = sc.new_file(root / "c.txt", "c\n")
        d = sc.new_file(root / "d.txt", "d\n")

        ctl.add(a)
        ctl.add(b, depends_on=[a])
        ctl.add(c, depends_on=[a])
        ctl.add(d, depends_on=[b, c])

        result = ctl.start(max_workers=4)
        print(f"\nctl ok = {result.ok}")
        for report in result.reports:
            print(f"  {report.node_name}: {report.outcome.value}")


if __name__ == "__main__":
    main()
