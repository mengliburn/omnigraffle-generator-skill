# omnigraffle-generator-skill

An agent skill (Claude Code / GitHub Copilot CLI) that turns **Mermaid diagrams into
editable OmniGraffle documents** — flat objects, connectors that are really connected, one
diagram per canvas.

Not screenshots, and not an imported blob. Real OmniGraffle shapes and lines you can drag.

```bash
$S/make_native_graffle.sh diagrams.graffle DESIGN.md
```

Markdown in, verified multi-canvas `.graffle` out.

## Why this exists

OmniGraffle's SVG importer is lossy in ways that are **invisible in a browser**:

- every flowchart shape imports **blank** (Mermaid uses `<foreignObject>`; OmniGraffle ignores it)
- multi-line labels **collapse** and stop being centred (sibling `<tspan>`s get merged)
- **black boxes** appear behind edge labels (OmniGraffle can't parse `rgba()`)
- **arrowheads vanish**, and junk shapes land at the origin (it renders `<marker>` *definitions*
  as objects, and doesn't apply them)
- long identifiers **split mid-word** — a Mermaid bug where edge labels ignore `wrappingWidth`

And even fixed, an imported SVG gives you **only `ShapedGraphic`s**: nested 6 groups deep, with
the arrowhead as a separate object and no real connections.

So the preferred path skips the importer entirely and writes OmniGraffle's own object model.

## Install

```bash
git clone https://github.com/mengliburn/omnigraffle-generator-skill.git
cp -r omnigraffle-generator-skill/omnigraffle-generator ~/.claude/skills/
```

Then ask your agent for *"mermaid to omnigraffle"*.

## Two modes

| | **Native** (preferred) | **SVG import** |
|---|---|---|
| Grouping | none — flat | nested, 6 deep |
| Arrows | line + arrowhead are one object | two objects |
| Connections | real — lines re-route when a box moves | none |
| Layout | tightened to text, compacted | Mermaid's spacing |
| Diagrams | flowcharts, sequence diagrams | anything Mermaid renders |
| Needs OmniGraffle | no | yes |

Native output is tightened: shapes are sized to their text using OmniGraffle's *own* metrics
(calibrated against its auto-fit — identical to the unit), the layout is compacted rank by
rank, and connectors are two-point lines clipped to the box borders.

## Scripts

```bash
S=~/.claude/skills/omnigraffle-generator/scripts
```

| Script | Purpose |
|---|---|
| `make_native_graffle.sh` | **Start here.** Markdown/`.mmd` → verified multi-canvas `.graffle` |
| `extract_mermaid.py` | Pull ```` ```mermaid ```` blocks out of Markdown, named from their headings |
| `render_mermaid.sh` | Render `.mmd` → SVG; provisions the toolchain; patches Mermaid's edge-label wrap bug |
| `extract_flowchart_layout.mjs` / `mermaid_flowchart_to_graffle.py` | Native flowchart → `.graffle` (nodes, subgraphs, connected edges) |
| `extract_sequence_layout.mjs` / `mermaid_sequence_to_graffle.py` | Native sequence diagram → `.graffle` (participants, lifelines, messages, notes) |
| `merge_graffle.py` | Merge single-canvas files into one multi-canvas document |
| `verify_graffle.py` | Check every invariant, no OmniGraffle needed |
| `graffle_lib.py` | Shared plist emitters (RTF text, shapes, connected lines, geometry) |
| `og_fix_svg.mjs` | SVG path — rewrite an SVG so OmniGraffle imports it faithfully |
| `verify_svg.py` | SVG path — structural + text-completeness checks |
| `combine_svgs.py` | SVG path — merge SVGs into one (ID namespacing + transform baking) |
| `svg_to_graffle.sh` / `make_multicanvas.sh` | SVG path — import and assemble via OmniGraffle |
| `dump_graffle_text.applescript` | Read text back **out of** OmniGraffle |

## How multi-canvas works

OmniGraffle's automation can't do it: clipboard paste is silently ignored, and `duplicate`
fails across documents (`Can't make ... into type reference`).

So it happens at the **file level**. A `.graffle` is a ZIP whose `data.plist` holds a `Sheets`
array — one entry per canvas. Sheets are merged directly, offsetting graphic `ID`s per sheet
since they restart near 0 in every file.

## Verification stance

A browser screenshot proves nothing about OmniGraffle, and structural checks on a file don't
prove OmniGraffle parsed it. `verify_graffle.py` reads the plist back and checks nested groups,
connector midpoints, endpoints off their box border, labels blanketing a line, overlapping
shapes, canvas flexibility, page breaks, and — given the `.mmd` sources — that every label
fragment survived.

Every one of those checks exists because that defect shipped at least once.

## Requirements

- `node` + `npm` — the Mermaid toolchain is provisioned automatically on first run
- `python3` — stdlib only
- macOS + OmniGraffle — only for SVG-import mode; native generation and verification need neither

## License

MIT
