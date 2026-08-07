# JSL FlowLens

**Understand any JMP script.** Load JSL files, Python scripts, JMP Notebooks,
a whole `.jmpaddin`, or pasted code — and get a plain-language explanation plus
an animated, traceable visualization of how it runs.

Version 0.6.0 · JMP 18+ · MIT License

---

## Why

Someone hands you a JSL script — inherited from a colleague, exported from
Workflow Builder, or downloaded as an add-in. Before you can trust it, change
it, or explain it to someone else, you have to work out what it actually does.
FlowLens does that reading for you: it reconstructs the order of execution,
names the side effects, and points at the exact lines responsible.

## Requirements

- **JMP 18 or newer** — Python is built in and available immediately, with no
  setup step (neither `Python Init()` nor `Python Connect()` is used)
- **A web browser** — the result opens as a local HTML file

Nothing else. No pip packages, no internet connection, no server.

## Install

Double-click `JSL_FlowLens_vX.Y.Z.jmpaddin`. The add-in appears under
**Add-Ins > JSL FlowLens**.

Upgrading from a build before v0.2.4? Remove the older entry first in
**View > Add-Ins** — earlier releases used a different add-in ID and would
otherwise sit alongside the new one.

## Supported inputs

| Input | What FlowLens does with it |
|---|---|
| `.jsl` | Full JSL analysis. `Python Submit(...)` blocks are followed **into** the Python they run, and `Python Send` / `Python Get` are shown as the hand-overs they are. |
| `.py` | Parsed with Python's own grammar: imports, functions, control flow, and JMP API calls (`jmp.open`, `jmp.DataTable`, `dt.new_column`, …). `jmp.run_jsl('''…''')` is followed **into** the embedded JSL. |
| `.jmpnb` | JMP Notebooks: sections, text blocks and code cells in document order, each cell analysed in its own language. |
| `.jmpaddin` | Unpacked; every script inside is analysed and the menu entry point detected. |
| Pasted code | JSL or Python — the language is detected from the content. |

Because the two languages call each other in both directions, a single
analysis can cross the boundary several times. Every step keeps the line
number of the **real** file, so a Python line inside a JSL string still points
at its true location in the `.jsl`.

Beyond JSL constructs, the Python side recognises package installs
(`jmputils.jpip`), data-frame I/O (`read_parquet`, `to_csv`, …), plots, and
model fits — naming the estimator (`IsolationForest`, `LinearRegression`)
rather than the variable it was assigned to.

## Use

1. **1. Load your files/scripts** — add `.jsl`, `.py` or `.jmpnb` files, load a
   `.jmpaddin`, or paste code into the second tab. Files and pasted code can be
   combined. *Clear all* (below the tabs) empties both.
2. **2. Analyze** — click it. The result opens in your default browser as a
   single self-contained HTML file you can save or e-mail.
   *Start script (advanced)* lets you choose which file runs first; `(auto)`
   detects it correctly in almost every case.

## The four views

| View | What it shows |
|---|---|
| **Flow** | One lane per file, functions as nodes. Nodes light up in inferred execution order; call arrows animate. |
| **Flowchart** | A real flowchart: diamonds for decisions, parallelograms for I/O, loop-back arrows for repetition — plus a palette listing every function and the steps at which it is called. |
| **Storyboard** | A review table: *what happens* · *which component and phase it belongs to* · *the code itself*. Switch between **By component** (grouped under each function) and **Full flow** (start to finish). Each row has a tick box for sign-off. |
| **Coverage** | The complete script with every line colour-coded: green once the walk-through has reached it, blue for lines represented but not yet reached, **amber for executable lines no step represents at all**. |

Play, pause and step controls apply to all three; the current step stays in
sync when you switch views. Arrow keys step, space plays.

**Traceability.** Every element carries its `file : line`. The `‹/›` link opens
the exact code extract, or the complete script with those lines highlighted and
scrolled into view. Calls additionally jump to the called function's definition.

## Reviewing a script end to end

FlowLens is meant to be usable as a review instrument, not just a diagram:

1. Step through the flow. In **Coverage**, every line a step touches turns
   green, so you can see what you have and have not looked at.
2. Watch the counter: *"127 of 141 code lines reached · 14 not represented"*.
   The amber lines are the honest part — code that FlowLens's model does not
   cover (typically plain assignments and data manipulation with no side
   effect). Those are exactly the lines to read yourself. Clicking a green
   line jumps to the step that owns it.
3. Tick steps off in the **Storyboard** as you satisfy yourself they are
   correct. Ticks are remembered per script while the page stays open, and
   *Tick all up to here* signs off everything you have already walked through.
4. **Print / Save as PDF** produces a review document: overview, the full step
   table with your ticks, a per-file coverage summary, and an explicit list of
   the line numbers nothing represents.

## What it recognises

**JSL:** functions and expressions · `Include()` chains · calls · decisions ·
loops · Workflow Builder steps (`step_name`) · data tables · columns · windows ·
file I/O · 16 report platforms · table operations · log messages · errors ·
top-level settings variables.

**Python:** imports · functions and classes · calls · decisions · loops ·
`jmp` API use (open, create table, add column) · package installs · data-frame
reads and writes · plots · model fits · prints.

**Cross-language:** `Python Submit` / `Python Send` / `Python Get` from JSL, and
`jmp.run_jsl` from Python.

Trivial helpers (short, no side effects, no control flow) are detected and
folded away so they don't clutter the main story — a checkbox brings them back.

## AI explanation (optional)

The rule-based explanation always works, offline, with nothing configured. For
a richer narrative there are two optional routes:

- **Copy AI prompt** — copies a ready-made prompt to the clipboard. No key, no
  configuration, no network call from JMP. Paste it into whichever AI chat you
  are permitted to use, then bring the answer back with *Paste AI answer*.
- **Ask AI via API** — sends the script text to an endpoint you configure
  (Anthropic, any OpenAI-compatible service, or a corporate endpoint) under
  *AI settings*. Nothing is transmitted without an explicit confirmation click
  naming the endpoint.

**Privacy note.** Analysis itself never leaves the machine and the generated
HTML contains no external references. The API route is the single exception,
and only on request. The API key is stored in plain text in
`$DOCUMENTS/JSL_FlowLens_Settings.txt` — on a shared machine, prefer the
clipboard route.

## Honest limitations

- The flow is **inferred from static analysis, not a runtime trace.** Your
  script is read, never executed — no tables are created, no windows opened,
  no files written. The interface states this on every screen.
- Both sides of a decision are walked; loops are shown once with a repeat
  marker. Real iteration counts are unknowable without running the code.
- Very large scripts stop at 400 steps (helper calls are folded away first).
- The code must be parseable. A syntactically broken script produces a clear
  error rather than a diagram.

## Languages

- **Interface and explanations:** English and German, switchable in the header
  and in the generated page. Additional languages are additive — one table per
  language in each of the two files.
- **Analysed:** JSL (hand-written, multi-file, packaged add-ins, Workflow
  Builder exports), Python (`.py` and embedded blocks), and JMP Notebooks —
  including code that crosses from one language into the other.

## Files

| File | Role |
|---|---|
| `FlowLens.jsl` | The add-in: dialog, Python bridge, AI options, EN/DE interface |
| `flowlens_parser.py` | Parser and model builder — Python standard library only |
| `flowlens_template.html` | Visualization template; the model is injected into it |
| `demo/` | A three-file example application ("Quality Snapshot") |
| `icon.png`, `logo_256.png` | Menu icon and listing logo |

## Provenance

JSL FlowLens is an **independent, original tool**, written from scratch. It is
not affiliated with, endorsed by, or supported by SAS Institute or the JMP
division, and it is not a JMP product.

A different, third-party JSL visualization add-in was examined beforehand to
understand what such a tool could do. FlowLens shares **no code, no interface
layout, no visual design and no sample files** with it; the parser, the
execution-order model, the three views, the traceability system and the
bundled demo scripts are all original work. The capability overlap — reading
JSL and drawing a diagram — is inherent to the problem, not derived.

## License

MIT — see `LICENSE.txt`. Copyright (c) 2026 Florian.

---

# Development

## Repository layout

```
VERSION                     single source of truth for the version number
src/                        the add-in itself
  FlowLens.jsl              dialog, Python bridge, AI options, EN/DE interface
  flowlens_parser.py        parser and model builder (standard library only)
  flowlens_template.html    visualization template
  Addin.def, addin.jmpcust  add-in metadata and menu entry
  icon.png, logo_256.png
demo/
  quality_snapshot/         three-file example application
  architecture/             an add-in whose dialog launches two sub-tools
build/build_addin.py        stamps the version and packages the .jmpaddin
docs/                       presentation and other material
reference/                  third-party material - not committed (see .gitignore)
dist/                       build output - published via Releases, not committed
```

## Building

```bash
python build/build_addin.py --check   # verify sources, stamp nothing
python build/build_addin.py           # write dist/JSL_FlowLens_v<VERSION>.jmpaddin
```

The build reads `VERSION`, stamps it into `FlowLens.jsl`, `flowlens_parser.py`
and this README, runs a smoke test that parses the demo with the packaged
parser, then writes an uncompressed archive with `Addin.def` first - the shape
JMP's own Add-In Builder produces, which JMP requires.

To release a new version: edit `VERSION`, add a `CHANGELOG.md` entry, run the
build, and attach the resulting `.jmpaddin` to a GitHub Release.

## Getting the repository onto GitHub

Keep the working copy **outside** any cloud-synced folder - OneDrive and git
both manage file state and interfere with each other's locks.

```bash
# copy this folder to a local path first, e.g. C:\dev\jsl-flowlens
git init
git add .
git commit -m "JSL FlowLens v0.5.0"
git branch -M main
git remote add origin https://github.com/flovo87/jsl_flowlens.git
git push -u origin main
```

Start with a **private** repository: `reference/` contains third-party material,
and a public repository counts as publication.
