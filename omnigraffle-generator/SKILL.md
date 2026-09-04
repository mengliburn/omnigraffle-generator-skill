---
name: omnigraffle-generator
description: |
  Convert Mermaid diagrams into SVGs that OmniGraffle imports faithfully, and assemble
  them into a single multi-canvas .graffle document (one diagram per canvas). Handles the
  OmniGraffle SVG-importer limitations that silently destroy text, colour and layout.

  Trigger: "mermaid to omnigraffle", "omnigraffle svg", "open diagram in omnigraffle",
  "multi-canvas graffle", "omnigraffle-generator"
user-invocable: true
allowed-tools: ["Bash", "Read", "Write", "Edit", "Grep", "Glob"]
---

# OmniGraffle Generator

Turn Mermaid diagrams into **editable OmniGraffle vector art**, not screenshots.

A stock `mmdc` SVG *looks* correct in a browser and imports into OmniGraffle almost
entirely broken. Every transform in this skill exists because of a specific, observed
OmniGraffle importer limitation — see [Why each step exists](#why-each-step-exists).
Do not skip steps because the SVG "looks fine"; a browser will not show you any of these
failures.

`$SKILL` below is this skill's directory.

---

## Two modes — pick one

| | **Native** (preferred) | **SVG import** |
|---|---|---|
| Output | OmniGraffle's own objects, written straight into `data.plist` | SVG, imported by OmniGraffle |
| Grouping | none — flat objects | deeply nested groups (6 levels, 40+ groups) |
| Arrows | line + arrowhead are **one** object | line and arrowhead are two objects |
| Connections | real `Head`/`Tail` — lines re-route when a box moves | none; lines merely end near a box |
| Diagram support | flowcharts + sequence diagrams | anything Mermaid renders |

Use **native** for flowcharts and sequence diagrams. Fall back to **SVG import** for
diagram types with no native mapping (class, state, ER, gantt, pie), or when you want an
SVG for a browser or GitHub as well.

---

## Native mode

```bash
python3 $SKILL/scripts/extract_mermaid.py DOC.md out/mmd      # optional
$SKILL/scripts/render_mermaid.sh out/raw out/mmd/*.mmd        # do NOT run og_fix_svg

# flowchart
node $SKILL/scripts/extract_flowchart_layout.mjs out/raw/x.svg > x.json
python3 $SKILL/scripts/mermaid_flowchart_to_graffle.py x.json x.graffle --title "Title"

# sequence diagram
node $SKILL/scripts/extract_sequence_layout.mjs out/raw/y.svg > y.json
python3 $SKILL/scripts/mermaid_sequence_to_graffle.py y.json y.graffle --title "Title"

# one document, one diagram per canvas
python3 $SKILL/scripts/merge_graffle.py -o all.graffle "x.graffle=01 · X" "y.graffle=02 · Y"
```

Pick the extractor by inspecting the SVG: `grep -q messageLine` means sequence diagram.

**Native mode reads Mermaid's semantic markup, so it must run on the raw render — before
`og_fix_svg.mjs`, which deliberately destroys that markup.**

### Facts the emitters depend on

All established by drawing the equivalent objects in OmniGraffle and reading the plist back:

- `GraphicsList` is **front-to-back** — the first entry draws on top. Emit labels first,
  lines last, or connectors paint over the labels that are supposed to mask them.
- A `LineGraphic` **without `LogicalPath` is silently discarded** on load.
- Shape text is **RTF**, and RTF is cp1252 — non-ASCII must use `\uN?` escapes or `—`
  arrives as `â€"`.
- Connections are `Head`/`Tail` `{"ID": n}`, and the target may be a `ShapedGraphic` **or
  another `LineGraphic`**.
- Nested subgraphs must be emitted smallest-first, or the outer container paints over the
  inner one.

### Sizing and line simplification

- **Boxes are tight to their text**, matching OmniGraffle's own auto-fit exactly.
  Measuring the SVG is *not* good enough: OmniGraffle lays our RTF (`Helvetica \fs24`) out
  at 12 canvas units per em, while the SVG renders at 16px, so an SVG-derived width is 4/3
  too large. The extractors therefore measure with `canvas.measureText` at **12px
  Helvetica**, and a line box is exactly **14 units** tall once `Text.Pad`/`VerticalPad`
  are zeroed. Verified against OmniGraffle's `autosizing: full`: identical to the unit on
  every rectangle. `Wrap: NO` is set because the bounds are exactly the text width.
  `--pad-x`/`--pad-y` (default 0) add breathing room if wanted. Only plain rectangles are
  tightened — cylinders, stadiums and subroutines keep Mermaid's height, since their caps
  need the room. Centres are preserved, so connected edges simply re-route.
- **The layout is compacted rank by rank after the shapes shrink.** Mermaid positions nodes
  for its own padded boxes, so tightening the shapes leaves every connector far longer than
  it needs to be. A single uniform scale does not work: it is dominated by the worst edge in
  the diagram, so one wide label keeps every other connector long. Dagre lays nodes out in
  ranks along one axis, so each gap between consecutive ranks is closed independently, down
  to `--edge-gap` (default 16) plus the widest label crossing *that* gap. Neighbours within
  a rank are closed up to `--node-gap` as well, otherwise diagonal edges stay long. Order
  and cross-axis alignment are preserved.
- **Connectors are clipped to the tightened shapes.** Mermaid routes edges against its own
  padded containers, so once the shapes shrink the original endpoints sit well outside them
  and leave a visible gap. Each polyline is re-anchored at the box centres and clipped to
  the borders, which puts the ends (and the arrowhead) back on the edge. The same applies to
  sequence-diagram lifelines after the participant boxes are tightened.
- **Connectors are plain two-point lines.** Mermaid's routed polyline carries midpoints even
  on a dead-straight edge, which show up in OmniGraffle as stray handles. Each connector is
  rebuilt as a single segment between the two box centres, clipped to their borders, so it
  has exactly two points. Self-loops keep their route because they need one, and
  `--keep-routing` restores Mermaid's polylines. Anything still routed is passed through
  `--simplify-tol` (default 6) to drop collinear leftovers — including sequence-diagram
  lifelines, where clipping otherwise leaves the old endpoints behind.

### Canvas settings

Every canvas is written flexible rather than fixed: `CanvasSizingMode = 1`
(what OmniGraffle writes for `adjusts pages = true`), so it grows on every side as
content moves, and `PageBreaks = 'NO'` so no page-break rules are drawn across the
diagram. `HPages`/`VPages` are seeded at 1 and OmniGraffle recalculates them from the
content.

### Why sequence-diagram messages are not connected

OmniGraffle **re-routes a connected line to its target's connection point as soon as the
document loads**. Attaching messages to lifelines collapsed all 11 messages onto a single
y (72.5), destroying the timeline. A message means "at this point in time", so position
wins: lifelines are connected to their participant boxes, messages are left free.
`--connect-messages` opts in, and will flatten the diagram.

---

## SVG-import mode

### Step 1 — Get the Mermaid sources

From a Markdown file:

```bash
python3 $SKILL/scripts/extract_mermaid.py DOC.md OUTDIR/mmd
```

It writes `NN-<slug>.mmd` per ```` ```mermaid ```` block, naming each from the nearest
preceding heading, and prints `name<TAB>title` lines. **Keep those titles** — reuse them
as diagram titles in Step 4 and canvas names in Step 5.

If the user already has `.mmd` files, skip this.

### Step 2 — Render to SVG

```bash
$SKILL/scripts/render_mermaid.sh OUTDIR/svg OUTDIR/mmd/*.mmd
```

Provisions `@mermaid-js/mermaid-cli` into `~/.cache/omnigraffle-generator/toolchain` on
first run (one time, ~20 s), renders with `htmlLabels:false`, and patches Mermaid's
edge-label wrapping bug.

### Step 3 — Make the SVGs OmniGraffle-safe

```bash
node $SKILL/scripts/og_fix_svg.mjs OUTDIR/svg/*.svg     # edits in place
```

This is the core of the skill. It reports what it changed per file.

**Verify before continuing** — this catches the failures that are invisible in a browser:

```bash
for f in OUTDIR/svg/*.svg; do
  n=$(basename "$f" .svg)
  python3 $SKILL/scripts/verify_svg.py "$f" "OUTDIR/mmd/$n.mmd"
done
```

Every file must print `OK`. `missing=N` means label text was lost or split mid-word — stop
and investigate rather than shipping it.

At this point the individual SVGs are usable: they open correctly in OmniGraffle **and**
still render normally in a browser / on GitHub.

### Step 4 — (optional) One combined SVG

For a single flat file containing every diagram stacked vertically with titles:

```bash
python3 $SKILL/scripts/combine_svgs.py -o OUTDIR/all-diagrams.svg \
  "OUTDIR/svg/01-foo.svg=1. First diagram" \
  "OUTDIR/svg/02-bar.svg=2. Second diagram"
```

Must report `dup_ids=0, unresolved_refs=0, leftover_transforms=0`.

### Step 5 — (optional) Multi-canvas .graffle

For one native OmniGraffle document with **one diagram per canvas** — usually what people
actually want:

```bash
$SKILL/scripts/make_multicanvas.sh OUTDIR/diagrams.graffle \
  "OUTDIR/svg/01-foo.svg=01 · First diagram" \
  "OUTDIR/svg/02-bar.svg=02 · Second diagram"
```

Requires OmniGraffle installed; it drives the app via AppleScript (there is no headless
mode) and will focus it repeatedly. Each canvas is auto-sized to its own diagram.

### Step 6 — Verify in OmniGraffle

Structural checks do not prove OmniGraffle parsed the file. Read the text back out:

```bash
osascript $SKILL/scripts/dump_graffle_text.applescript FILE.graffle
```

Compare against the `.mmd` label fragments. Text present per canvas, with nothing bleeding
between canvases, is the only real pass condition.

---

## Why each step exists

Each row is a real OmniGraffle behaviour, confirmed by reading geometry and text back out
of OmniGraffle via AppleScript. **All of these render correctly in a browser**, which is
why they are so easy to ship broken.

| OmniGraffle behaviour | Symptom if unhandled | Handled by |
|---|---|---|
| Ignores `<foreignObject>` | Every flowchart shape imports **blank**. Mermaid puts flowchart labels in embedded XHTML by default | `render_mermaid.sh` (`htmlLabels:false`) |
| Merges sibling `<tspan>`s into one left-aligned paragraph, ignoring per-tspan `x` / `text-anchor` | Multi-line labels collapse and stop being centred in their shape | `og_fix_svg.mjs` — one `<text>` per row |
| Cannot parse `rgba()` (not valid SVG 1.1 paint); falls back to **black** | Black boxes behind edge labels | `og_fix_svg.mjs` — `rgb()` + `*-opacity` |
| Ignores the `<style>` block | Shapes lose all fill/stroke/font | `og_fix_svg.mjs` — inline computed styles |
| Renders `<marker>` **defs** as real objects, and does **not** apply them to paths | Arrowheads lost *and* a pile of junk shapes dumped at the origin | `og_fix_svg.mjs` — real `<polygon>` arrowheads, markers deleted |
| Draws zero-area rects as visible filled boxes | Stray boxes; Mermaid emits empty placeholder rects | `og_fix_svg.mjs` |
| Ignores **ancestor transforms** for some elements | Parts of a diagram scattered at raw coordinates when diagrams are offset for stacking | `combine_svgs.py` — bakes all transforms into coordinates |
| Mangles `<line>` | Lifelines collapse to 1×1 objects | `og_fix_svg.mjs` — `<line>` → `<path>` |
| Mermaid's `insertEdgeLabel()` passes `width: undefined`, so edge labels ignore `flowchart.wrappingWidth` and use a hardcoded 200px | Long identifiers hard-split **mid-word** (`requeueRequestsPCollectio` / `n`) | `render_mermaid.sh` patch |

### Automation limits (do not waste time here)

- **Clipboard copy/paste is ignored.** Scripted `⌘C`/`⌘V` between documents silently pastes nothing.
- **`duplicate` fails across documents** — `Can't make ... into type reference`.
- **`export` via AppleScript is unreliable** — `-10000` / `-1701` even with explicit settings.
- **`move` works within a single document**, but is fragile in bulk.

Multi-canvas assembly therefore happens **at the file level, not the GUI level**: a
`.graffle` is a ZIP whose `data.plist` holds a `Sheets` array, one entry per canvas.
`merge_graffle.py` merges sheets and offsets graphic `ID`s per sheet (they restart near 0
in every file, and `Head`/`Tail` connection references also carry `ID`).

---

## Rules

1. **Never skip `verify_svg.py`.** Every bug this skill exists for is invisible in a browser.
2. **Never claim OmniGraffle renders correctly from a browser screenshot.** Read the text
   back out of OmniGraffle, or say you did not verify it.
3. **Preserve the individual SVGs.** They stay valid for browsers/GitHub; the combined SVG
   and `.graffle` are additional artifacts, not replacements.
4. **Do not hand-edit generated SVGs.** Re-run the pipeline; the scripts are idempotent.
5. **Warn before Step 5** that OmniGraffle will be focused repeatedly and open documents
   will be closed (`close every document saving no`).

## Requirements

- `node` + `npm` (toolchain is provisioned automatically on first run)
- `python3` (stdlib only)
- OmniGraffle + macOS `osascript` — Steps 5 and 6 only
