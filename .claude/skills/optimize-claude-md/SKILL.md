---
name: optimize-claude-md
description: How to audit and optimize a project's CLAUDE.md (or AGENTS.md) for context efficiency and instruction-following. Use this skill whenever the user asks to optimize, slim down, refactor, audit, review, or improve their CLAUDE.md / AGENTS.md / agent instructions file — or mentions that CLAUDE.md feels bloated, that Claude is ignoring instructions, that the file has grown too long, or that they want to apply progressive disclosure / move things to skills. Also use proactively when editing a CLAUDE.md that visibly exceeds ~150 lines or contains code-style rules, "how to add X" recipes, or other task-specific content.
---

# Optimizing CLAUDE.md

CLAUDE.md is loaded into every session. It is the single highest-leverage prompt surface in the harness — and also the easiest one to ruin by overstuffing. The goal of this skill is to produce a CLAUDE.md that onboards Claude to the codebase quickly and contains only instructions that apply to *every* task.

## Why this matters

A few facts shape every editing decision:

- The model can reliably follow only ~150–200 instructions; Claude Code's built-in system prompt already burns ~50 of those before your project says anything.
- As instruction count grows, the model doesn't drop the "last" instructions — it follows *all* of them less reliably. Adding a niche rule degrades adherence to the important ones.
- The harness wraps CLAUDE.md in a system reminder that tells the model to ignore it if not relevant. Niche instructions don't just waste tokens — they make the model treat the whole file as more skippable.
- Context window space spent on irrelevant rules is space not spent on relevant code, tool results, and recent messages.

So the optimization target is not "comprehensive" — it is "universally applicable, concise, and impossible to ignore."

## Step 1 — Locate the file

Check, in order:
1. `./.claude/CLAUDE.md` (project-scoped, checked-in, common in this codebase family)
2. `./CLAUDE.md` (repo root)
3. `./AGENTS.md` (open-source equivalent — same rules apply)

If both `./CLAUDE.md` and `./.claude/CLAUDE.md` exist, ask the user which one to optimize (or optimize both, but treat them independently — don't merge).

## Step 2 — Read it with a critical eye

Read the current file end-to-end. For each section / bullet / paragraph, classify it into exactly one bucket:

- **Keep (universal):** True for essentially every task in this repo. Examples: "this is a Python library using `uv`", "tests live under `tests/`", "no real IO in tests".
- **Move to a skill:** Task-specific recipes — "how to add a new X", "how to wire up a new Y". These belong in `.claude/skills/<name>/SKILL.md` so they load only when relevant. Look especially for content that starts with "When adding…", "To create a new…", "For new <component>…".
- **Move to a reference doc:** Deep architectural notes, schema descriptions, communication patterns. Park in `agent_docs/<topic>.md` and reference from CLAUDE.md as a pointer ("Read `agent_docs/database_schema.md` if your task touches the schema.").
- **Delete (linter's job):** Code-style rules, formatting conventions, import ordering, naming conventions enforceable by a linter or formatter. Claude is in-context learner — it picks these up from the surrounding code. If the user feels strongly, suggest a Stop hook running the linter rather than restating the rules in prose.
- **Delete (derivable):** Anything Claude can recover by reading the code, running `git log`, or listing a directory. Don't restate the directory tree if `ls` is one tool call away.
- **Delete (stale / aspirational):** Rules the codebase doesn't actually follow, or notes about decisions long since made.

When in doubt about "universal vs task-specific": ask "would this instruction help on a task where the user just wants to fix a typo in a docstring?" If no, it's not universal.

## Step 3 — Rewrite around WHAT / WHY / HOW

A good CLAUDE.md answers three questions concisely:

- **WHAT** — what is this project, what's the stack, what's the high-level map (a few directories, not the full tree).
- **WHY** — what is the project for; why do the major pieces exist. Helps the model make judgement calls when instructions don't cover a case.
- **HOW** — how to do meaningful work: how to run the project, run tests, type-check; any non-obvious tooling (`uv` instead of `pip`, `bun` instead of `node`, custom scripts).

Then, only after those, a short "universal rules" section and a "task-specific guides" section pointing at skills and reference docs.

## Step 4 — Aim for a length target

There is no hard cap, but these are useful anchors:

- **< 60 lines** — excellent. HumanLayer's own root CLAUDE.md is ~60 lines.
- **< 150 lines** — fine for most repos.
- **< 300 lines** — upper bound before the file starts working against itself.
- **> 300 lines** — almost always a sign that progressive disclosure has been skipped.

Length is a symptom, not the disease. A 40-line file full of niche rules is worse than a 120-line file of universally applicable ones. But if you can't get under 150 lines, you probably haven't extracted enough into skills.

## Step 5 — Extract content into skills, not just into the trash

When you remove a "how to add X" section, don't just delete it — the knowledge is real, it just lives at the wrong level. Create `.claude/skills/<name>/SKILL.md` with a frontmatter `description` written in pushy, trigger-friendly language so the harness loads it at the right moment. Reference the file you're extracting from so future editors can trace the move.

A good extracted skill description:
- Names the concrete trigger phrases ("create", "add", "implement a new …").
- Names adjacent triggers too — operations the user might describe without using the canonical term.
- Tells the harness when to load it proactively, not just when explicitly asked.

After extraction, the corresponding CLAUDE.md entry collapses to one line: `Adding a new <thing> → invoke the <skill-name> skill.`

## Step 6 — Review your draft cold

Set the draft aside, then re-read it as if you'd never seen the project. For each line, ask:

- Is this true for *every* task, or only some?
- Does removing this line cause the model to make a mistake it otherwise wouldn't?
- Is this information the model could trivially recover from the codebase?
- Am I telling the model *why*, or just barking *what*? Explanations of why a rule exists make the model handle edge cases gracefully; bare rules don't.

Cut anything that fails. Then show the user the diff (or the before/after line counts) so they can sanity-check the cuts.

## Anti-patterns to watch for

- **The "hotfix" pile-up.** A list of one-off rules added each time the model misbehaved. These erode adherence to the rules that actually matter. Better: ask whether the misbehavior recurs across tasks. If not, drop the rule.
- **Code snippets restating conventions.** "Always use `def foo(x: int) -> int:` style with type hints" plus a 6-line example. Replace with "Type hints on every signature."
- **Embedded code samples that drift.** A snippet showing the canonical pattern will rot. Prefer a file:line pointer to a real reference implementation in the repo.
- **Re-stating the directory tree.** `ls` does this for free. Keep the map at the "what lives in which top-level folder" level only.
- **Telling the model what it already knows.** "Be careful", "write clean code", "follow best practices" — pure noise.
- **Auto-generated `/init` output left as-is.** Treat any boilerplate-feeling CLAUDE.md as a first draft, not a finished file.

## When the user pushes back

Some users feel that more instructions = more control. They're not wrong about leverage — CLAUDE.md is high-leverage — but they're wrong about the curve. Explain that instruction-following degrades across *all* instructions as count grows, not just the new ones, and offer the skill / reference-doc move as a way to *keep* the content available without paying the per-session cost. The information isn't lost; it's loaded on demand.

If they still want a specific rule kept inline, keep it. The user's judgement about their codebase wins; this skill's job is to surface the trade-off, not enforce it.
