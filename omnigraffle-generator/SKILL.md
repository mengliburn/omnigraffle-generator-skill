---
name: omnigraffle-generator
description: |
  Convert Mermaid diagrams into editable OmniGraffle documents — flat objects, connectors
  that are really connected, one diagram per canvas. Also produces SVGs that survive
  OmniGraffle's importer. Encodes the OmniGraffle file-format and importer behaviour needed
  to get this right.

  Trigger: "mermaid to omnigraffle", "omnigraffle diagram", "open diagram in omnigraffle",
  "multi-canvas graffle", "omnigraffle svg", "omnigraffle-generator"
user-invocable: true
allowed-tools: ["Bash", "Read", "Write", "Edit", "Grep", "Glob"]
---

# OmniGraffle Generator

Turn Mermaid diagrams into **editable OmniGraffle vector art**, not screenshots.

`$SKILL` below is this skill's directory. Everything here was established by generating
files, reading them back out of OmniGraffle, and fixing what was wrong — the
[behaviour tables](#omnigraffle-behaviour-that-drives-the-design) are observations, not
guesses. Trust them over intuition; several are the opposite of what you would expect.

---

## Two modes — use native unless you can't

| | **Native** (preferred) | **SVG import** |
|---|---|---|
| How | writes OmniGraffle's object model into `data.plist` | writes an SVG, OmniGraffle imports it |
| Grouping | none — flat objects | nested groups, 6 deep, 40+ per diagram |
| Arrows | line + arrowhead are **one** object | two separate objects |
| Connections | real `Head`/`Tail` — lines re-route when a box moves | none; lines merely end near a box |
| Layout | shapes tightened to text, layout compacted | Mermaid's spacing |
| Diagrams | flowcharts, sequence diagrams | anything Mermaid renders |
| Needs OmniGraffle | no | yes (no headless mode) |

The SVG importer **only ever produces `ShapedGraphic`** — not one `LineGraphic` — which is
why arrowheads and connections are impossible through it. Use SVG import only for diagram
types with no native mapping (class, state, ER, gantt, pie), or when you also want an SVG
for a browser or GitHub.

---

## Native mode

One command, Markdown in, verified document out:

```bash
$SKILL/scripts/make_native_graffle.sh OUT.graffle DOC.md
$SKILL/scripts/make_native_graffle.sh OUT.graffle a.mmd b.mmd
```

It extracts each ```` ```mermaid ```` block, renders it, picks the right extractor per
diagram (`grep -q messageLine` ⇒ sequence), builds one canvas each, merges, and runs
`verify_graffle.py`. Canvas titles come from the Markdown heading above each diagram.

The steps individually, if you need to tune one:

```bash
python3 $SKILL/scripts/extract_mermaid.py DOC.md out/mmd
$SKILL/scripts/render_mermaid.sh out/raw out/mmd/*.mmd      # do NOT run og_fix_svg here

node    $SKILL/scripts/extract_flowchart_layout.mjs out/raw/x.svg > x.json
python3 $SKILL/scripts/mermaid_flowchart_to_graffle.py x.json x.graffle --title "01 · X"

node    $SKILL/scripts/extract_sequence_layout.mjs  out/raw/y.svg > y.json
python3 $SKILL/scripts/mermaid_sequence_to_graffle.py y.json y.graffle --title "02 · Y"

python3 $SKILL/scripts/merge_graffle.py -o all.graffle "x.graffle=01 · X" "y.graffle=02 · Y"
python3 $SKILL/scripts/verify_graffle.py all.graffle out/mmd
```

**Native mode reads Mermaid's semantic markup, so it must run on the raw render — before
`og_fix_svg.mjs`, which deliberately destroys that markup.**

### Tuning

| Flag | Builder | Default | Effect |
|---|---|---|---|
| `--pad-x` / `--pad-y` | both | `0` | Breathing room around text. 0 = shape is exactly its text |
| `--edge-gap` | flowchart | `16` | Clear run on a connector beyond its own label |
| `--node-gap` | flowchart | `16` | Gap between neighbours within a rank |
| `--simplify-tol` | flowchart | `6` | Collinear tolerance when a routed polyline is kept |
| `--keep-routing` | flowchart | off | Keep Mermaid's polylines instead of straight connectors |
| `--no-compact` | flowchart | off | Keep Mermaid's spacing |
| `--connect-messages` | sequence | off | Attach messages to lifelines (**flattens the timeline**) |

---

## OmniGraffle behaviour that drives the design

### File format

| Fact | Consequence |
|---|---|
| A `.graffle` is a **ZIP** whose `data.plist` holds a `Sheets` array, one entry per canvas | Multi-canvas documents are built by merging plists, not through the GUI |
| `GraphicsList` is **front-to-back** — the first entry draws on top | Emit labels first, connectors last, or the lines paint over the labels meant to mask them |
| A `LineGraphic` **without `LogicalPath` is silently discarded** on load | Cost five lines with no error the first time |
| Shape text is **RTF**, and RTF is cp1252 | Non-ASCII needs `\uN?` escapes or `—` arrives as `â€"` |
| Arrowheads are `Style.stroke.HeadArrow` on the line | Line and arrow are one object |
| Connections are `Head`/`Tail` `{"ID": n}` | The target may be a `ShapedGraphic` **or another `LineGraphic`** |
| Graphic `ID`s restart near 0 in every file | Merging must offset them per sheet; `Head`/`Tail` refs renumber with them |
| `CanvasSizingMode` `1` = Flexible; `AutoAdjust` is a **per-side bitmask** | `15` = all four sides. `1` is top only — easy to get wrong |
| `PageBreaks = 'NO'` at document level | Otherwise page-break rules are drawn across wide diagrams |

### Text metrics

OmniGraffle lays our RTF (`Helvetica \fs24`) out at **12 canvas units per em**, while the
SVG renders at 16px — so an SVG-derived width is 4/3 too large. Measuring with
`canvas.measureText` at **12px Helvetica** reproduces OmniGraffle's widths to within 0.5%
(ratios 0.7473–0.7506 over four strings), and a line box is exactly **14 units** tall once
`Text.Pad`/`VerticalPad` are zeroed. Checked against `autosizing: full` — identical to the
unit on every rectangle. `Wrap: NO` is required because the bounds are exactly the text
width, and any sub-pixel difference would otherwise re-wrap the label.

### SVG importer limitations

All of these render **correctly in a browser**, which is why they are so easy to ship broken.

| Behaviour | Symptom | Handled by |
|---|---|---|
| Ignores `<foreignObject>` | Every flowchart shape imports **blank** | `render_mermaid.sh` (`htmlLabels:false`) |
| Merges sibling `<tspan>`s into one left-aligned paragraph | Multi-line labels collapse, stop being centred | `og_fix_svg.mjs` — one `<text>` per row |
| Cannot parse `rgba()`; falls back to **black** | Black boxes behind edge labels | `og_fix_svg.mjs` — `rgb()` + `*-opacity` |
| Ignores the `<style>` block | Shapes lose all fill/stroke/font | `og_fix_svg.mjs` — inline computed styles |
| Renders `<marker>` **defs** as objects, and doesn't apply them | Arrowheads lost **and** junk dumped at the origin | `og_fix_svg.mjs` — real `<polygon>` arrowheads |
| Draws zero-area rects as filled boxes | Stray boxes | `og_fix_svg.mjs` |
| Ignores **ancestor transforms** for some elements | Parts scattered at raw coordinates when diagrams are offset | `combine_svgs.py` — bakes transforms into coordinates |
| Mangles `<line>` | Lifelines collapse to 1×1 | `og_fix_svg.mjs` — `<line>` → `<path>` |

### Mermaid quirk

`insertEdgeLabel()` passes `width: undefined` to `createText()`, which falls back to a
hardcoded 200px and **ignores `flowchart.wrappingWidth`**, hard-splitting long identifiers
mid-word (`requeueRequestsPCollectio` / `n`). `render_mermaid.sh` patches it.

### Automation limits — do not waste time here

- **Clipboard copy/paste is ignored.** Scripted ⌘C/⌘V between documents pastes nothing.
- **`duplicate` fails across documents** — `Can't make ... into type reference`.
- **`export` is unreliable** — `-10000` / `-1701` even with explicit settings.
- **`set zoom` updates the property but not the view.** Use the View ▸ Zoom menu items
  (`Fit in Window`, `Zoom to Selection`); coordinate clicks on the toolbar are flaky, and
  another app can steal focus mid-screenshot — re-check `frontmost` before capturing.
- **`move` works within one document**; `autosizing: full` re-fits a shape that has no
  `FitText`, which is how the text metrics above were calibrated.
- OmniGraffle wedges occasionally; if AppleScript starts timing out, quit and relaunch it.

---

## Layout decisions

- **Shapes are tight to their text**, matching OmniGraffle's own auto-fit exactly. Only
  plain rectangles are tightened — cylinders, stadiums and subroutines keep Mermaid's
  height, since their caps need the room.
- **The layout is compacted rank by rank.** A single uniform scale does not work: it is
  dominated by the worst edge in the diagram, so one wide label keeps every other connector
  long, and dense diagrams refuse to compact at all. Dagre lays nodes out in ranks, so each
  gap between consecutive ranks is closed independently, down to `--edge-gap` plus the
  widest label crossing *that* gap. Neighbours within a rank are closed to `--node-gap`,
  otherwise diagonal edges stay long. Order and cross-axis alignment are preserved.
- **Connectors are plain two-point lines** between the two box centres, clipped to their
  borders — no stray midpoint handles, and both ends land exactly on the edge. Self-loops
  keep their route. Anything still routed goes through `--simplify-tol`, **including
  sequence-diagram lifelines**, where clipping otherwise leaves the old endpoints behind.
- **Labels are opaque and frontmost** so they mask the connector they name, and no label is
  allowed to blanket its whole line.
- **Nested subgraphs are emitted smallest-first**, or the outer container paints over the
  inner one.
- **Sequence messages are deliberately not connected.** OmniGraffle re-routes a connected
  line to its target's connection point on load, which collapsed all 11 messages onto
  y=72.5 and destroyed the timeline. A message means "at this point in time", so position
  wins. Lifelines *are* connected, to their top and bottom participant boxes.

---

## SVG-import mode

```bash
python3 $SKILL/scripts/extract_mermaid.py DOC.md out/mmd
$SKILL/scripts/render_mermaid.sh out/svg out/mmd/*.mmd
node    $SKILL/scripts/og_fix_svg.mjs out/svg/*.svg          # edits in place

for f in out/svg/*.svg; do                                    # never skip
  python3 $SKILL/scripts/verify_svg.py "$f" "out/mmd/$(basename "$f" .svg).mmd"
done

python3 $SKILL/scripts/combine_svgs.py -o out/all.svg "out/svg/01-a.svg=First"
$SKILL/scripts/make_multicanvas.sh out/diagrams.graffle "out/svg/01-a.svg=01 · A"
```

The fixed SVGs stay valid for browsers and GitHub, so they remain usable inline in docs.
`combine_svgs.py` must report `dup_ids=0, unresolved_refs=0, leftover_transforms=0`.

---

## Verification — this is the part people skip

A browser screenshot proves **nothing** about OmniGraffle, and structural checks on a file
do not prove OmniGraffle parsed it.

```bash
python3 $SKILL/scripts/verify_graffle.py FILE.graffle [MMD_DIR]   # native, no app needed
python3 $SKILL/scripts/verify_svg.py FILE.svg [FILE.mmd]          # SVG path
osascript $SKILL/scripts/dump_graffle_text.applescript FILE.graffle
```

`verify_graffle.py` checks nested groups, connector midpoints, endpoints off their box
border, labels blanketing a line, overlapping shapes, canvas flexibility and page breaks —
and, given the `.mmd` directory, that every label fragment survived. Every one of those
checks exists because that defect shipped at least once.

**Rules**

1. **Never claim it renders correctly without reading it back** — via `verify_graffle.py`
   or `dump_graffle_text.applescript`. Otherwise say you did not verify it.
2. **Never skip `verify_svg.py`** on the SVG path; those failures are invisible in a browser.
3. **Zoomed out, OmniGraffle draws text at a minimum legible size**, so tight boxes *look*
   like the text overflows. Check at ≥60% zoom before believing it.
4. **Don't hand-edit generated files** — re-run; the scripts are deterministic.
5. **Warn before any step that drives the app**: it takes focus and closes open documents
   (`close every document saving no`).
6. **Write to a new file** when regenerating something the user may have edited by hand.

## Requirements

- `node` + `npm` — the Mermaid toolchain is provisioned automatically on first run
- `python3` — stdlib only
- macOS + OmniGraffle — only for SVG-import mode and `dump_graffle_text.applescript`;
  native generation and `verify_graffle.py` need neither
