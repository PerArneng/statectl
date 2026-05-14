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
        dir_path = Path(tmp) / "subdir"
        file_path = dir_path / "hello.txt"

        ctl = StateCtl.new()
        sc = ctl.changers()

        ensure_dir = sc.ensure_directory(dir_path, mode=0o755)
        write_file = sc.new_file(file_path, "hello from statectl\n")

        ctl.add(ensure_dir)
        ctl.add(write_file, depends_on=[ensure_dir])

        ctl.start()

        print(f"--- contents of {file_path} ---")
        print(file_path.read_text())


if __name__ == "__main__":
    main()
