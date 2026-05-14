# statectl provisioning roadmap

A prioritized list of state changers and the capabilities they depend on, ordered by their importance for declaratively provisioning a fresh **macOS** or **Linux** machine. The ordering is capability-first: a state changer cannot land before the capability it needs. Within each tier, foundational file/config primitives come before network fetch, archives, package managers, and finally services and accounts.

Today the library ships:

- Capabilities: `FileSystem`, `ProcessRunner`, `Logger`.
- State changers: `NewTextFileStateChanger` (rollbackable), `RunCommandStateChanger` (sentinel-based).

That is enough to write files and run commands, but not enough to provision a machine. Everything below is what to build next.

---

## Capability roadmap (in build order)

| # | Capability | Proposed location | Purpose | Unlocks |
|---|---|---|---|---|
| 1 | `FileSystem` extensions | `_interfaces/fs/file_system.py` (same ABC, new methods) | `chmod`, `stat_mode`, `is_symlink`, `read_symlink`, `create_symlink`, `copy_file`, `read_binary_file`, `write_binary_file` | permissions, symlinks, binary downloads, archive extraction output |
| 2 | `HttpClient` | `_interfaces/http/` | `get(url, headers) -> HttpResponse`, `download_to_file(url, dest, headers)`; typed errors `HttpError`, `HttpNotFound`, `HttpServerError`, `HttpNetworkError`. Real impl wraps stdlib `urllib` (no new third-party dep) | downloads, package-manager bootstrap, remote config fetch |
| 3 | `Archive` | `_interfaces/archive/` | `extract(src, dest, format)` for `tar`, `tar.gz`, `tar.bz2`, `tar.xz`, `zip`. Real impl uses stdlib `tarfile` + `zipfile` — preferred over shelling out so we avoid BSD-vs-GNU `tar`/`unzip` flag drift | extracting downloaded tarballs |
| 4 | `Clock` | `_interfaces/clock.py` | `now()`, `monotonic()` | `details["duration_ms"]`, cache-staleness checks, retry/backoff |
| 5 | `Env` | `_interfaces/env.py` | `get(name)`, `user_home()`, `platform() -> "darwin" \| "linux"` | OS-branching in package-manager / service changers, `~` resolution |
| 6 | `Hashing` (optional) | `_interfaces/hashing.py` | `sha256_file(path)` | checksum verification for `DownloadFile` |

---

## State-changer roadmap

### Tier 1 — file & directory primitives (`FileSystem` only)

The bedrock. Almost every higher-tier changer composes with these.

1. **`EnsureDirectory`** — `mkdir -p` with optional mode. Rollbackable (delete if still empty). Idempotency: content-equiv (`exists` + `is_dir` + mode match).
2. **`EnsureLineInFile`** / **`AppendLineToFile`** — add a line to a config file if absent, optionally anchored by regex/match. Rollbackable (remove the line). Idempotency: content-equiv (line present).
3. **`ReplaceInFile`** — regex or literal substitution, optional `validate` callback. Rollbackable via captured original content. Idempotency: content-equiv (post-state already present).
4. **`SetFileMode`** (chmod) — Rollbackable (restore prior mode). Idempotency: content-equiv on mode bits. *Needs FS extension #1.*
5. **`EnsureSymlink`** — Rollbackable (delete link). Idempotency: content-equiv (target match). *Needs FS extension #1.*
6. **`DeleteFile`** / **`DeletePath`** — one-shot (delete is its own inverse only conceptually; we keep it non-rollbackable). Sentinel `removes`.
7. **`CopyFile`** / **`RenderTemplate`** — copy or render from a source path/string. Idempotency: content-equiv (post-state SHA match).

### Tier 2 — network fetch

Required before any package manager can be bootstrapped.

8. **`DownloadFile`** — fetch URL to path, optional `sha256`. Rollbackable (delete). Idempotency: file exists + checksum matches (or just exists if no checksum). *Needs `HttpClient`, optional `Hashing`.*
9. **`FetchUrlToString`** — fetch a small remote config for a downstream changer to consume. *Needs `HttpClient`.*

### Tier 3 — archives

10. **`ExtractArchive`** — extract tarball/zip into a directory. Sentinel-based (`creates=<marker path inside archive>`); not safely rollbackable in general (cannot reconstruct overwrites). *Needs `Archive` + `FileSystem`.*

### Tier 4 — package managers (the actual provisioning payoff)

11. **`EnsureHomebrewInstalled`** (macOS bootstrap) — runs the official install script. Sentinel `creates=/opt/homebrew/bin/brew` (Apple Silicon) or `/usr/local/bin/brew` (Intel). Not rollbackable. *Needs `HttpClient` + `ProcessRunner` + `Env`.*
12. **`BrewPackage`** — install/upgrade a brew formula. Rollbackable (uninstall). Idempotency: `brew list --formula <name>` exits 0. *Needs `ProcessRunner`.*
13. **`BrewCask`** — same shape, casks. Rollbackable. *Needs `ProcessRunner`.*
14. **`BrewTap`** — Rollbackable (untap). *Needs `ProcessRunner`.*
15. **`AptPackage`** (Debian/Ubuntu) — `apt-get -y install`. Rollbackable (`apt-get remove`). Idempotency: `dpkg -s <name>` exits 0. *Needs `ProcessRunner`.*
16. **`AptRepository`** — write `/etc/apt/sources.list.d/*.list` + signing key. Rollbackable. *Needs `FileSystem` + `HttpClient` (for key) + `ProcessRunner` (gpg/apt-key).*
17. **`AptUpdate`** — refresh package lists. One-shot. Sentinel: staleness check against apt lists mtime. *Needs `ProcessRunner` + `Clock` + `FileSystem`.*

### Tier 5 — git, runtimes, services

18. **`EnsureGitRepoCloned`** — clone at ref, or `git fetch` + checkout. Rollbackable (delete dir). Idempotency: dir exists + HEAD matches ref. *Needs `ProcessRunner` + `FileSystem`.*
19. **`EnsureLaunchdAgent`** (macOS) — write plist + `launchctl load`. Rollbackable (unload + remove plist). *Needs `FileSystem` + `ProcessRunner`.*
20. **`EnsureSystemdUnit`** (Linux) — write `.service` + `systemctl daemon-reload` + enable/start. Rollbackable. *Needs `FileSystem` + `ProcessRunner`.*
21. **`EnsureService`** — thin façade dispatching to launchd vs systemd via `Env.platform()`.

### Tier 6 — accounts, shells, dotfiles

22. **`EnsureUser`** — Linux: `useradd`, macOS: `dscl`. Rollbackable. *Needs `ProcessRunner` + `Env`.*
23. **`EnsureGroupMembership`** — Rollbackable. *Needs `ProcessRunner`.*
24. **`EnsureDefaultShell`** — `chsh`. Rollbackable (restore prior shell). *Needs `ProcessRunner` + `Env`.*

---

## Out of scope (deliberately deferred)

- Windows / PowerShell DSC equivalence.
- Container and VM provisioning; cloud APIs (AWS / GCP / Azure SDKs).
- Secret material (Keychain, libsecret, gpg-agent) — needs a dedicated `SecretStore` capability design.
- Idempotent firewall rules (pf / iptables / nftables) — non-trivial state diffing.
- Reboot orchestration and multi-host fan-out.
