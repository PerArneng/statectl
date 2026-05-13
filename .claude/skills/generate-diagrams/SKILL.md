---
name: generate-diagrams
description: How to generate diagrams of the statectl codebase. Two tools are wired up — pydeps (module/import dependency graph) and pyreverse (UML class + package diagrams). Use this skill whenever the user asks to visualize, diagram, draw, graph, render, or "show me" the project's structure, architecture, imports, modules, classes, inheritance, or package relationships — or when answering an architecture question would benefit from a generated picture. Pick the tool by what the user wants to see: module-level imports → pydeps; class hierarchies and attributes → pyreverse classes; package containment → pyreverse packages.
---

# Generating diagrams

Two tools are wired up. Both render via Graphviz (`dot` must be on PATH); both write into `diagrams/` at the repo root; the folder is in `.gitignore` — outputs are never committed. Share them as attachments instead.

| Question | Tool | Default output |
|---|---|---|
| "How do my modules import each other?" | **pydeps** | `diagrams/statectl.png` |
| "Show me the class hierarchy / classes and their attributes" | **pyreverse** | `diagrams/classes_statectl.png` |
| "How are packages laid out / what's inside what" | **pyreverse** | `diagrams/packages_statectl.png` |

## Happy paths

```bash
task diagram      # pydeps module graph
task diagram-uml  # pyreverse class + package diagrams (one invocation, two PNGs)
task diagrams     # all of the above
```

If the user just asks for "the diagram" without a qualifier, run `task diagrams` and report all output paths.

## When to deviate

### pydeps (module imports)

Always pass `--noshow` so it doesn't auto-open a browser. **Always pass `-T png` (or `-T svg`) explicitly** — pydeps does *not* infer the format from the `-o` extension and will silently write SVG content into a `.png`-named file otherwise.

| User wants | Command |
|---|---|
| Default project graph | `task diagram` |
| Whole repo incl. tests/examples | `uv run pydeps . --noshow -T png -o diagrams/all.png` |
| Only one package | `uv run pydeps statectl/interfaces --noshow -T png -o diagrams/interfaces.png` |
| Include third-party deps | add `--externals` to any pydeps command |
| Trim a too-dense graph | add `--max-bacon=2` (or `=3`) |
| Arrows point *to* importer | add `--reverse` |
| SVG instead of PNG | swap `-T png` → `-T svg` and the `.png` extension |

### pyreverse (UML classes + packages)

`pyreverse` always emits **both** a `classes_<name>.<ext>` and a `packages_<name>.<ext>` file from one invocation — you get both whether you wanted both or not. The `-p <name>` flag controls the filename suffix.

| User wants | Command |
|---|---|
| Default UML pair | `task diagram-uml` |
| Include inheritance ancestors | add `-A` |
| Include associated classes | add `-S` |
| Only show public members | add `--filter-mode=PUB_ONLY` |
| Only one subpackage | `uv run pyreverse -o png -p statechangers -d diagrams statectl/statechangers` |
| SVG instead of PNG | swap `-o png` → `-o svg` |

## Output format

Default to PNG — it's the project preference (renders inline in chats, docs, and PR descriptions without extra tooling). Use SVG only when the user explicitly asks for it, or when the graph is large enough that PNG raster quality hurts readability.

## Output naming

Always into `diagrams/`. Suffix by scope so variants don't overwrite each other: `statectl.png`, `all.png`, `interfaces.png`, `externals.png`, `classes_statectl.png`, `packages_statectl.png`.

## When Graphviz is missing

Both tools shell out to `dot`. If `command -v dot` returns nothing:

- macOS: `brew install graphviz`
- Debian/Ubuntu: `sudo apt install graphviz`
- Windows: <https://graphviz.org/download/> and add `dot` to PATH

## Don't over-explore first

This skill is invoked because the user already wants a picture. Pick the tool, run the right invocation, report the output path(s). No pre-exploration of the codebase needed.
