---
name: generate-diagrams
description: How to generate diagrams of the statectl codebase. Two tools are wired up — pydeps (module/import dependency graph) and pyreverse (UML class + package diagrams). Both render PNGs; pyreverse can also emit text formats (Mermaid `.mmd`, PlantUML `.puml`, Graphviz `.dot`) for docs and diffs, and pydeps can emit JSON/DOT for querying the import graph. Use this skill whenever the user asks to visualize, diagram, draw, graph, render, or "show me" the project's structure, architecture, imports, modules, classes, inheritance, or package relationships — or asks for diagram source in Mermaid/PlantUML/DOT — or when answering an architecture question would benefit from a generated picture. Pick the tool by what the user wants to see: module-level imports → pydeps; class hierarchies and attributes → pyreverse classes; package containment → pyreverse packages.
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
task diagram           # pydeps module graph (PNG)
task diagram-uml       # pyreverse class + package diagrams (PNG pair)
task diagram-uml-mmd   # pyreverse class + package diagrams as Mermaid text
task diagram-uml-puml  # pyreverse class + package diagrams as PlantUML text
task diagrams          # all of the above (PNGs + Mermaid + PlantUML)
```

If the user just asks for "the diagram" without a qualifier, run `task diagrams` and report all output paths.

## When to deviate

### pydeps (module imports)

Always pass `--noshow` so it doesn't auto-open a browser. **Always pass `-T png` (or `-T svg`) explicitly** — pydeps does *not* infer the format from the `-o` extension and will silently write SVG content into a `.png`-named file otherwise.

| User wants | Command |
|---|---|
| Default project graph | `task diagram` |
| Whole repo incl. tests/examples | `uv run pydeps . --noshow -T png -o diagrams/all.png` |
| Only one package | `uv run pydeps statectl/_interfaces --noshow -T png -o diagrams/interfaces.png` |
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
| Only one subpackage | `uv run pyreverse -o png -p statechangers -d diagrams statectl/_statechangers` |
| SVG instead of PNG | swap `-o png` → `-o svg` |
| Mermaid text (renders in GitHub/Notion) | swap `-o png` → `-o mmd` (or run `task diagram-uml-mmd`) |
| PlantUML text | swap `-o png` → `-o puml` (or run `task diagram-uml-puml`) |
| Raw Graphviz DOT source | swap `-o png` → `-o dot` |

## Output format

Default to PNG — it's the project preference (renders inline in chats, docs, and PR descriptions without extra tooling). Use SVG only when the user explicitly asks for it, or when the graph is large enough that PNG raster quality hurts readability.

### Text formats (pyreverse)

`pyreverse` can emit text source instead of (or alongside) an image — useful when the user wants something diffable, greppable, or embeddable in docs without an image attachment. `task diagrams` produces both PNG and text variants by default.

| Format | Extension | When to use |
|---|---|---|
| **Mermaid** | `.mmd` | Renders inline in GitHub Markdown, Notion, many docs viewers — paste between ```` ```mermaid ```` fences and it just works. Best "informative + portable" text option. |
| **PlantUML** | `.puml` | Same idea as Mermaid but for PlantUML-based doc pipelines. |
| **Graphviz DOT** | `.dot` | When you want to script edits (filter nodes, recolor) before re-rendering with `dot`. |

Both `.mmd` and `.puml` include class attributes, method signatures, and inheritance/association edges — they're a textual, more informative companion to the PNG, not a stripped-down version.

### Text outputs (pydeps)

pydeps can emit text artifacts in addition to images — useful when the user wants to *query* the import graph rather than look at it:

| Flag | Output | When to use |
|---|---|---|
| `--show-deps` | JSON dep map (use shell redirect `> file.json`) | Programmatic queries like "who transitively imports X?" |
| `--show-dot` / `--dot-output FILE` | Graphviz DOT source | Hand-edit the graph before re-rendering. |
| `--show-cycles` | Text listing of import cycles | Quick "are there any cycles?" check. |

These are not wired into the Taskfile because they're situational; run them directly when the user asks. Pair with `--no-output` to skip image generation.

## Output naming

Always into `diagrams/`. Suffix by scope so variants don't overwrite each other: `statectl.png`, `all.png`, `interfaces.png`, `externals.png`, `classes_statectl.png`, `packages_statectl.png`. Text companions share the stem and swap extension: `classes_statectl.mmd`, `classes_statectl.puml`, etc.

## When Graphviz is missing

Both tools shell out to `dot`. If `command -v dot` returns nothing:

- macOS: `brew install graphviz`
- Debian/Ubuntu: `sudo apt install graphviz`
- Windows: <https://graphviz.org/download/> and add `dot` to PATH

## Don't over-explore first

This skill is invoked because the user already wants a picture. Pick the tool, run the right invocation, report the output path(s). No pre-exploration of the codebase needed.
