#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = ["statectl"]
#
# [tool.uv.sources]
# statectl = { path = "../", editable = true }
# ///
#
# NOTE: this example demonstrates the API proposed in the
# "Variable registry: share outputs between state changers" GitHub issue.
# It will not run until that issue is implemented. It is checked in alongside
# the issue so the proposed surface can be reviewed end-to-end.
#
# Flow modelled here: "provision a local DB-like thing"
#   1. ensure_directory  -> publishes `data_dir`        (Path)
#   2. run("openssl ...") -> publishes `db_password`     (str, from stdout)
#   3. new_file(config)   -> deferred; reads `data_dir` + `db_password`
#   4. new_file(schema)   -> deferred; reads `data_dir`, depends on (3)
import logging
import tempfile
from pathlib import Path

from statectl import StateCtl


CONFIG_TEMPLATE = """\
[database]
data_dir = "{data_dir}"
password = "{password}"
"""

SCHEMA_SQL = """\
CREATE TABLE accounts (
    id   INTEGER PRIMARY KEY,
    name TEXT NOT NULL
);
"""


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    with tempfile.TemporaryDirectory() as tmp:
        data_dir = Path(tmp) / "db"

        ctl = StateCtl.new()
        sc = ctl.changers()

        # --- Step 1: ensure data directory exists; publish its resolved path.
        ensure_dir = sc.ensure_directory(data_dir, mode=0o755)
        ctl.add(
            ensure_dir,
            publishes=lambda ch, _res: {"data_dir": ch.params.path},
        )

        # --- Step 2: generate a password by running a command; publish stdout.
        # `creates=` makes the run idempotent: second run sees the marker and
        # is skipped, with `publishes` still firing (ALREADY_APPLIED path).
        pw_marker = data_dir / ".password"
        gen_password = sc.run(
            ["sh", "-c", f"openssl rand -hex 16 | tee {pw_marker}"],
            creates=pw_marker,
        )
        ctl.add(
            gen_password,
            publishes=lambda _ch, res: {
                "db_password": res.details.get("stdout", "").strip()
            },
        )

        # --- Step 3: write config.toml, needs BOTH data_dir and db_password.
        # The factory runs after ensure_dir + gen_password have published.
        # registry.require(name, as_type=T) is where the cast happens.
        write_config = ctl.add_deferred(
            lambda reg: sc.new_file(
                reg.require("data_dir", as_type=Path) / "config.toml",
                CONFIG_TEMPLATE.format(
                    data_dir=reg.require("data_dir", as_type=Path),
                    password=reg.require("db_password", as_type=str),
                ),
            ),
            depends_on=[ensure_dir, gen_password],
        )

        # --- Step 4: write schema.sql once config exists.
        ctl.add_deferred(
            lambda reg: sc.new_file(
                reg.require("data_dir", as_type=Path) / "schema.sql",
                SCHEMA_SQL,
            ),
            depends_on=[write_config],
        )

        result = ctl.start(max_workers=4)

        print(f"engine ok: {result.ok}")
        print("captured variables:")
        for name, value in ctl.registry().snapshot().items():
            # never print secrets in real code; this is a demo.
            print(f"  {name} = {value!r}")


if __name__ == "__main__":
    main()
