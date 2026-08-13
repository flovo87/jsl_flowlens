# Changelog

All notable changes to JSL FlowLens are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/); this project
uses [semantic versioning](https://semver.org/).

## [0.8.0] — 2026-08-07

The Flow view's capabilities carried across to the other three views, as noted
in `docs/BACKLOG.md`.

### Added
- **One shared control strip.** Layout, filters, search, zoom and focus now sit
  in a single bar whose sections appear according to the active view, instead
  of being available only in Flow.
- **Search, in every view** — a single box that highlights matching items in
  Flow, matching nodes in the Flowchart, filters rows in the Storyboard and
  highlights matching lines in Coverage, with a match count.
- **Flowchart**: zoom in / out / reset (it could already exceed 1800 px on the
  small architecture demo), a shape legend, focus by double-click that keeps a
  node's ancestors and sub-tree and dims every other path, and a
  *Structure only* filter that strips effect nodes down to the skeleton.
- **Storyboard**: filters per phase, each with its count, and *Unreviewed only*
  for working through what is still unsigned.
- **Coverage**: *Gaps only* plus *Prev gap* / *Next gap* navigation, and a
  font-size zoom for long files.

## [0.7.0] — 2026-08-07

Final item of the continuous-improvement list (item F).

### Added
- **The flowchart shows architecture instead of one strand.** Every button in
  a dialog is now a *choice*: the parser cuts each button's action out of the
  surrounding statement and walks it as its own path, so alternatives are no
  longer reported as if they all ran in sequence. The flowchart lays the steps
  out as a tree - sequential steps stack downwards, alternative choices fan out
  side by side, each with its own sub-tree.
- Choice nodes are drawn as purple decision shapes with their own connectors,
  and are explained as "this path runs only if the user picks it".
- `Run JSL File`, `Run Program` and add-in installs are recognised as launches
  of a sub-application.

### Notes
- On the bundled `demo/architecture` example - a launch pad whose four buttons
  run different tools - the four choices now sit in parallel at the same level,
  each above what it actually does. Previously all of it appeared as one
  sequence, which is what prompted this change.

## [0.6.0] — 2026-08-07

Second batch of the continuous-improvement list (items B, D and E).

### Added
- **Variables are graph items.** The parser now finds every top-level
  assignment and works out which component writes it and which reads it, so
  the Flow view shows producer → variable → consumer chains with directed
  **read** (blue, dashed) and **write** (orange, dashed) links.
- **Four layouts** for the Flow view — hierarchical (layered by call depth),
  swimlane (one lane per file), circular and grid.
- **Show/hide filters** per item type — scripts, functions, expressions,
  variables, dataflow — each showing its count.
- **Zoom** in / out / reset, and **focus**: double-click an item to dim
  everything not connected to it, with a *Clear focus* button.
- A legend for item kinds and link types.

### Changed
- **JMP colour scheme throughout.** Orange `#FE5A22` for actions and the
  current step, blue `#1570C8` for structure and calls, purple `#92509E` for
  expressions and Python, dark blue `#0B3D75` for script roots. Coverage
  states moved onto the same palette: blue for reached, orange for the gaps.

## [0.5.0] — 2026-08-07

First batch of the continuous-improvement list (items A, C and G).

### Fixed
- **Coverage now accounts for every executed line.** Statements that produce
  no recognised effect - plain assignments and computation such as
  `a = Abs(v)` - previously generated no step, so a function that was walked
  still looked half-checked. Each such statement now gets a quiet step of its
  own, hidden behind *Show plain statements* but always counted. Loop headers
  and branch conditions are excluded, so `For(i = 1, ...)` no longer produces
  three spurious entries.
- Walking past a visible step now also counts the hidden steps between it and
  the previous one, so display filters can no longer change the coverage
  figures.
- The result: the parquet-importer example goes from 19 of 22 lines with three
  gaps to **22 of 22, no gaps**; the demo and the notebook example reach 100 %
  represented.

### Changed
- **Decluttered.** The explanation sidebar is collapsed by default (toggle
  *Explanation*), and speed, filters and the print button moved into a
  collapsed *Options* bar. The top row is now just views, transport and the
  two toggles.
- **Flowchart panels no longer overlap.** The code link moved inside the node
  onto the reference line, the file/line label is left-aligned beside it, and
  the sidebar is organised into collapsible sections (settings, one per file,
  helpers).

## [0.4.1] — 2026-08-04

### Fixed
- **Coverage no longer depends on the display filters.** "Represented" is now
  computed from every step in the model; hiding log messages or helper calls
  used to make those lines look unrepresented.
- **Configuration variables reported the wrong line number** (off by the blank
  and comment lines preceding them), so they never lined up in the coverage
  view.

### Added
- A fifth coverage state, **explained elsewhere** (grey): function and
  expression definition scaffolding, declared settings, and housekeeping
  statements such as `Names Default To Here(1)`. These are visible in the
  function palette or the settings panel rather than as flow steps.
  Amber therefore now means one thing only: executable code that nothing in
  the model explains.

## [0.4.0] — 2026-08-03

### Added
- **Coverage view ("lens").** The complete script, line by line: green once
  the walk-through reaches a line, blue for lines represented but not yet
  reached, amber for executable lines that **no step represents**. Per-file
  counters, a progress bar, a file picker, and click-a-line-to-jump-to-its-step.
  The amber lines are deliberately prominent — they show where the model is
  thin, so a reviewer knows exactly what to read by hand.
- **Storyboard rebuilt as a review table**: *what it does* · *belongs to*
  (owning component plus an inferred phase: Setup / Data preparation /
  Analysis / Output / Control flow) · *the code*, with a **By component /
  Full flow** toggle. Grouped mode collects the steps under each function.
- **Reviewer sign-off**: a tick box per step, a signed-off counter,
  *Tick all up to here*, *Clear ticks*, and best-effort persistence.
- **Print / Save as PDF**: a dedicated print layout producing a review
  document — overview, full step table including ticks, per-file coverage
  summary, and the list of line numbers nothing represents.
- Parser exports `code_ranges` per file, so notebooks count only their code
  cells rather than the container syntax.

### Changed
- All controls share one shape, height and radius; the view switcher and the
  transport buttons are evenly spaced, and the transport buttons have a fixed
  width so differing glyph widths no longer distort them.

## [0.3.0] — 2026-08-03

### Added
- **Python support.** `.py` files are parsed with Python's own grammar
  (`ast`): imports, functions and classes, control flow, calls, and the JMP
  Python API (`jmp.open`, `jmp.DataTable`, `dt.new_column`). Also recognised:
  package installs via `jmputils.jpip`, data-frame reads and writes, plots,
  and model fits — labelled with the estimator (`IsolationForest`) rather than
  the variable it was assigned to.
- **JMP Notebook support** (`.jmpnb`): sections, text blocks and code cells in
  document order, each cell analysed in its own language.
- **Cross-language analysis in both directions.** JSL `Python Submit(...)` is
  followed into the Python it runs; Python `jmp.run_jsl('''...''')` is followed
  into the embedded JSL. `Python Send` / `Python Get` appear as explicit
  hand-over steps.
- Language badges on lanes, files and steps; Python steps are tinted green in
  the flowchart, so a language change is visible at a glance.
- New step types (import, embedded block, notebook cell, section, text) and
  effect kinds (plot, model, packages), in English and German.
- JSL effects now also recognised: `Pick File` / `Pick Directory`,
  `Column Dialog`, and platform messages sent to any object
  (`dt << Graph Builder(...)`), not only to a named data table.

### Changed
- File picker accepts `.jsl`, `.py` and `.jmpnb`; labels and hints updated.
- Pasted code: the language is detected from the content.

### Notes
- Embedded code keeps the line numbers of the **real** file, so a Python line
  inside a JSL string still points at its true location in the `.jsl`.

## [0.2.6] — 2026-07-31

### Fixed
- Removed the call to the **deprecated `Python Init()`**. Python ships with
  JMP 18 and is available immediately — no initialisation step is required,
  and `Python Connect()` is only needed when a connection object is wanted.
  Availability is now confirmed with a one-line `Python Submit` probe, so a
  genuinely broken bridge still produces a clear message.
- Reworded the Python error message and the requirements in the README and
  the overview deck accordingly.

## [0.2.5] — 2026-07-31

### Added
- Menu icon (`icon.png`) and a 256 px logo for listings.
- `CHANGELOG.md`.
- README: provenance statement, privacy note on the AI route, limitations
  section.

## [0.2.4] — 2026-07-31

### Changed
- Add-in ID is now `FVT.JSLFlowLens` (was `FTV.JSLFlowLens`). Installations of
  earlier builds must be removed manually in **View > Add-Ins**.

## [0.2.3] — 2026-07-30

### Changed
- *Entry file* moved into a collapsed sub-section **Start script (advanced)**
  with a two-line explanation of what it does.
- *Settings* renamed **AI settings** and moved into the AI section, where it
  belongs — it only ever held endpoint, model and API key.
- Language switch lifted out of the settings dialog into the window header,
  always visible and applied immediately.

## [0.2.2] — 2026-07-30

### Changed
- Whole dialog inset with an outer margin; version and build date moved to
  their own line beneath the title.

## [0.2.1] — 2026-07-30

### Added
- Header band: product name in brand blue, tagline, version and build date,
  accent rule.
- Live status line reporting what is currently loaded, green when ready.

### Changed
- Consistent typography and colour tokens; every style message applied
  defensively so unsupported spellings cannot break the layout.

## [0.2.0] — 2026-07-30

### Changed
- **Renamed from "JSL ScriptLens" to "JSL FlowLens"** — product name, add-in
  ID, source file names, generated page branding and settings file.
- Window title now carries product name, add-in version and build date.
- AI section starts collapsed; wider spacing between the three sections.

## [0.1.x] — 2026-07-30 (development series, not publicly released)

Highlights of the pre-release iterations:

- **0.1.13** Full traceability: every step carries its statement source and
  line numbers; code viewer with *Extract* / *Full script* toggle, highlighted
  lines and jump-to-definition.
- **0.1.12** Fixed file import (`Pick File` multi-select flag was passed as a
  string, so the call failed); tooltips and inline hints on every control;
  *Clear all* moved below the tabs to reflect its wider scope.
- **0.1.11** Result opens directly in the system browser; the embedded browser
  box proved unreliable across JMP versions.
- **0.1.10** Dialog restructured into numbered outlines with File Selection /
  Paste Code tabs; pasting moved inline.
- **0.1.9** Workflow Builder support: `step_name` narration, table operations,
  report platforms; function names may contain spaces and any casing.
- **0.1.8** Circular loop-back arrows in the flowchart; loop and decision
  source code viewable.
- **0.1.7** Helper functions classified and de-emphasised; flowchart redrawn
  in true 2D with classic shapes and orthogonal connectors.
- **0.1.6** Flowchart view with static function palette and adjustable-settings
  box; fixed step banner replaced the floating tooltip.
- **0.1.5** Every independent root script is walked, including pasted code;
  click a function to view its source.
- **0.1.4** Readability pass: multi-column lanes, auto-scroll to the current
  step, log-message filter, storyboard view.
- **0.1.3** Step-limit handling made graceful; function bodies expanded once.
- **0.1.2** Fixed JMP-to-Python path conversion and parser loading.
- **0.1.1** Add-in packaged uncompressed, matching JMP's Add-In Builder.
- **0.1.0** First working build: Python parser, HTML visualization, demo
  scripts, JSL dialog.
