# Backlog

## Done in v0.8.0 — Flow improvements carried into the other views

The table below is kept for reference; every row marked "—" for Flowchart,
Storyboard or Coverage has since been addressed, except where noted under
"Still open" at the bottom.

## Original note (Monday session)

v0.6.0 and v0.7.0 gave the **Flow** view a set of capabilities the other three
views did not get. They should be applied consistently, so that switching view
does not mean losing controls.

What Flow has today:

| Capability | Flow | Flowchart | Storyboard | Coverage |
|---|:--:|:--:|:--:|:--:|
| Layout options (hierarchical / swimlane / circular / grid) | ✔ | — | n/a | n/a |
| Show/hide filters per item type, with counts | ✔ | — | — | — |
| Zoom in / out / reset | ✔ | — | n/a | — |
| Focus: dim everything unrelated | ✔ | — | — | — |
| Legend | ✔ | — | n/a | ✔ |
| JMP colour scheme | ✔ | ✔ | ✔ | ✔ |
| Dataflow (read/write links) | ✔ | — | — | — |

### Flowchart
- **Zoom is the urgent one.** With parallel choices the canvas already reaches
  ~1800 px wide on the small `demo/architecture` example; a real add-in will be
  far wider. Needs zoom in/out/reset and ideally fit-to-width.
- Filters: hide effect kinds (logs, table operations) and hide whole branches,
  so a large tree can be reduced to its skeleton.
- Focus: pick a choice or a function and dim every path that does not lead
  through it — the natural question is "what happens if the user clicks *this*".
- Legend for the shapes: rounded = start/include, rectangle = call, diamond =
  decision, purple diamond = user choice, parallelogram = I/O.
- Collapse a sub-tree from its parent node (fold a choice's branch away).

### Storyboard
- Filters: by phase (Setup / Data / Analysis / Output / Control flow), by
  component, by language, and "unreviewed only".
- Column visibility, since the code column dominates on narrow screens.
- Sort within a group (by line number vs. execution order).

### Coverage
- Filter to **gaps only**, plus *next gap* / *previous gap* navigation — the
  point of the view is finding what nothing explains.
- Zoom or font-size control for long files.
- Per-file summary table when several files are loaded, instead of a picker
  that shows one file at a time.

### Cross-cutting
- **Search.** No view has one. The reference visualizer has a search box over
  expressions, functions and variables; FlowLens should be able to find a name
  and jump to it in whichever view is open.
- The four views should share one control strip, so layout / filter / zoom /
  focus / search behave identically wherever they apply.

## Also outstanding

- **Provenance statement** in the README still says FlowLens shares no design
  with the JSL Script Visualizer. Now that the collaboration is in place and
  the dataflow model has been adopted, this needs rewording — best phrased
  together with its author.
- **Overview deck** (`docs/JSL_FlowLens_How_It_Works.pptx`) still describes the
  three-view version, before Coverage, the review table, Python/notebook
  support and the architecture flowchart.
- Publishing questions from the earlier pre-release review are still open:
  employer clearance, a second-machine test (especially "Python unavailable"),
  and whether to keep persisting the API key in plain text.

## Still open after v0.8.0

- **Flowchart**: fold a choice's sub-tree away from its parent node (collapse),
  and fit-to-width as a zoom preset.
- **Storyboard**: column visibility and sorting within a group.
- **Coverage**: per-file summary table when several files are loaded, instead
  of a picker showing one file at a time.
- Layout options do not apply to the Flowchart, which uses its own tree layout
  by design.
