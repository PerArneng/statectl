---
name: github-task-workflow
description: How to drive statectl roadmap work through GitHub Issues and the Project v2 Kanban board on PerArneng/statectl — picking the next task, moving cards Todo → In Progress → Done, linking branches and PRs, and listing or filtering board state. Use this skill whenever the user wants to start, claim, progress, finish, list, or look up a roadmap task — including phrases like "what's next", "I'm starting on #N", "move this to in progress", "what's left in Tier 2", "show the board", "mark this done", "where's the board URL", or any request to update project column / status. Also use when adding a fresh issue to the board after creating it via the new-state-changer or new-capability flow. Always prefer the bundled scripts in this skill's `scripts/` directory over hand-writing GraphQL — the scripts already encode the project's node IDs and the lookup-then-edit dance.
---

# Driving statectl tasks via GitHub Issues + Project board

## The setup

- **Repo**: `PerArneng/statectl` — all issues live here.
- **Board**: `https://github.com/users/PerArneng/projects/1` (Project v2, linked to the repo, currently **private**).
- **Status column** values: `Todo`, `In Progress`, `Done`.
- **Custom fields** on items: `Tier` (Capabilities, Tier 1…Tier 6) and `Kind` (Capability, State changer).
- **Issue labels** mirror the fields: `kind:capability`, `kind:state-changer`, `tier-cap`, `tier-1`…`tier-6`.
- **Roadmap source of truth**: `docs/roadmap.md`. The board is just a flight tracker; new work always starts from a roadmap entry.

`gh` needs the `repo`, `project`, and `read:project` scopes. If a board mutation 401s, refresh:

```
gh auth refresh -h github.com -s project,read:project
```

## Bundled scripts (use these instead of raw GraphQL)

All three live in `scripts/` next to this file and are executable. They encode the project number, field IDs, and option IDs — so the call site stays one line.

| Script | Purpose |
|---|---|
| `scripts/set-status.sh <N> <todo\|in-progress\|done>` | Move issue `#N`'s card to the named column. Fails loudly if the issue isn't on the board. |
| `scripts/add-to-board.sh <N> <cap\|1\|2\|3\|4\|5\|6> <cap\|sc>` | Add an existing issue to the board, set Tier + Kind + Status=Todo, and apply matching `tier-*` / `kind:*` labels in one shot. |
| `scripts/list-board.sh [todo\|in-progress\|done]` | Print the board as a table (`# / Status / Tier / Title`), optionally filtered to one status. |

Prefer running these over reproducing their GraphQL inline. If something fails, read the script — the IDs and queries are right there.

## Useful URLs

- **Board**: https://github.com/users/PerArneng/projects/1
- **All open issues in roadmap order**: `https://github.com/PerArneng/statectl/issues?q=is%3Aissue+is%3Aopen+sort%3Acreated-asc`
- **One tier** (swap label): `https://github.com/PerArneng/statectl/issues?q=is%3Aissue+is%3Aopen+label%3Atier-2+sort%3Acreated-asc`
- **Capabilities only**: `https://github.com/PerArneng/statectl/issues?q=is%3Aissue+label%3Akind%3Acapability+sort%3Acreated-asc`
- **Single issue**: `https://github.com/PerArneng/statectl/issues/<N>`

## The end-to-end workflow

The board reflects what's actually in flight. The card moves *before* the code does — that's what makes "what's everyone working on?" answerable at a glance.

### 1. Pick the next task

Default rule: take the lowest-numbered open issue whose dependencies (listed in the issue body) are all `Done`. Capabilities always precede the changers that depend on them; never start a changer whose capability is still `Todo`.

```
scripts/list-board.sh todo
```

For repo-wide context (e.g. counts per tier), use the URLs above.

### 2. Claim it — move to In Progress *first*

```
scripts/set-status.sh <N> in-progress
gh issue edit <N> --repo PerArneng/statectl --add-assignee @me
```

Doing this before you start typing is what keeps the board honest. If you skip this and start coding, the board lies about what's in flight.

### 3. Open a linked branch

`gh issue develop` creates a branch, links it to the issue (so the issue page shows it), and checks it out in one step:

```
gh issue develop <N> --repo PerArneng/statectl --base main --name issue-<N>-<short-kebab-slug> --checkout
```

Naming convention: `issue-<N>-<short-kebab-slug>` (e.g. `issue-7-ensure-directory`). It's a convention, not enforced — pick something the next reader can scan.

### 4. Build, committing with the issue reference

Use the issue number in commit messages so GitHub cross-links commits onto the issue timeline:

```
git commit -m "Add FileSystem.chmod and stat_mode (#1)"
```

For the actual implementation work, defer to whichever skill matches: `new-capability` for capabilities, `new-state-changer` for state changers, `statectl-architecture` for design questions. This skill is about the workflow, not the code.

### 5. Open a PR that closes the issue

```
gh pr create --repo PerArneng/statectl --base main --title "<short title>" --body "$(cat <<'EOF'
## Summary
- <bullet>

Closes #<N>

## Test plan
- [ ] task check passes
- [ ] new tests cover assess/transition (and rollback if applicable)
EOF
)"
```

The `Closes #<N>` line is load-bearing — when the PR merges, GitHub auto-closes the issue and the Project v2 built-in workflow moves the card from `In Progress` to `Done`. If you forget it, the card sticks in `In Progress` and you have to nudge it with `set-status.sh <N> done` manually.

### 6. After merge, verify

```
gh issue view <N> --repo PerArneng/statectl --json state,closedAt
scripts/list-board.sh done | head
```

## Adding new items to the board

When a new issue lands (e.g. `new-state-changer` produced one):

```
# Create the issue (typically done by another skill or `gh issue create`)
# Then attach it to the board:
scripts/add-to-board.sh <N> <tier> <kind>
```

`<tier>` is `cap` or `1`–`6`. `<kind>` is `cap` (capability) or `sc` (state changer). The script handles board membership, Tier, Kind, Status=Todo, and the matching `tier-*` + `kind:*` labels.

## When IDs go stale

The bundled scripts have project / field / option IDs hard-coded. They're stable as long as the project and its fields aren't recreated. If a script fails with "node not found" or similar, the IDs need re-resolving. Run:

```bash
gh api graphql -f query='
query {
  user(login:"PerArneng") {
    projectV2(number:1) {
      id
      fields(first:20) {
        nodes {
          ... on ProjectV2SingleSelectField { id name options { id name } }
        }
      }
    }
  }
}' | jq '.data.user.projectV2 | {project_id: .id, fields: .fields.nodes}'
```

Patch the IDs in the affected script(s). The project number (`1`) is referenced by `gh project ...` calls — change it there too if the project was recreated.

## Conventions / guardrails

- **Card before code.** Always `set-status.sh in-progress` before you start working. The most common drift is forgetting this and the board going stale.
- **One card In Progress per concurrent thread of work.** It's fine to have a capability and a dependent changer both In Progress if you're building them together — just don't park cards in In Progress that you aren't actively touching.
- **`Closes #N` in the PR body** is what triggers the auto-move to Done. Treat it as non-optional.
- **Don't close issues as "done" without merging the change.** The board reflects shipped state. For abandonment, close with a comment + `wontfix` label and move the card to Done explicitly.
- **Don't make the project public** without explicit user consent — it's intentionally private.
- **Never edit fields directly via the GitHub UI when a script could do it** — the scripts are the audit trail. UI edits are fine for things scripts don't cover (renaming views, dragging cards around within a column, etc.).

## What this skill is *not* about

- **Creating new issues from scratch** — handled by `new-capability` / `new-state-changer`, which produce the issue. This skill picks up afterwards (`add-to-board.sh`).
- **Designing the change** — see the architecture / changer / capability skills.
- **Releasing or tagging** — separate concern.
