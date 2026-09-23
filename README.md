<p align="center">
  <img src="docs/logo/cpnpy-logo.svg" alt="CPNpy" width="560">
</p>

<p align="center">
  <b>A modern take on ProM and CPN IDE, in one app: process mining, Petri nets and coloured Petri nets.</b><br>
  Pure Python + Qt. No Java, no Wine, no separate simulator to install.
</p>

![Drawing a WF-net and checking its soundness](docs/screenshots/petri-analysis.png)

**CPNpy Studio** brings together what usually takes several tools:

| | What you can do | Instead of |
|---|---|---|
| **Petri nets & WF-nets** | Draw nets the way the lectures do. Get a soundness verdict with a counterexample for every violation, and replay it in the token game. Also: behavioural properties, the footprint matrix, the reachability graph, PNML import and export. | WoPeD, ProM, pen and paper |
| **Process mining** | Import XES or CSV logs, or type textbook logs like `[<a,b,c>^3, <a,c>^2]`. Explore variants, the dotted chart and the process map. Discover models (α-algorithm, Inductive Miner, Heuristics). Check conformance (token replay, alignments, precision…) and compare logs. | ProM |
| **Coloured Petri nets** | Open, edit and save CPN Tools models (`.cpn`). Step through or simulate them, compute the state space, and export a simulation as an event log to mine. | CPN Tools / CPN IDE |

---

## Contents

- [Install](#install)
- [Quick start](#quick-start)
- [Petri nets and WF-nets](#petri-nets-and-wf-nets)
- [Process mining](#process-mining)
- [Coloured Petri nets](#coloured-petri-nets)
- [Working on the canvas](#working-on-the-canvas)
- [Keyboard shortcuts](#keyboard-shortcuts)
- [Files](#files)
- [For developers](#for-developers)
- [Limitations and roadmap](#limitations-and-roadmap)

---

## Install

CPNpy runs in a **conda** environment called `cpnpy`, defined in
`environment.yml`. If you don't have conda yet, install
[Miniforge](https://github.com/conda-forge/miniforge), which is native on
Apple Silicon:

```bash
brew install miniforge
conda init zsh                      # once; then open a new terminal
```

Get the code and create the environment:

```bash
git clone <the URL of this repository>    # the green "Code" button on GitHub
cd CPNpy
conda env create -f environment.yml     # Python 3.12, PySide6, pytest, CPNpy itself
conda activate cpnpy
```

Start the app:

```bash
cpnpy-studio
```

After pulling changes that touch `environment.yml` or `pyproject.toml`, run
`conda env update -f environment.yml --prune`.

> CPNpy is developed and tested on macOS. As a Python + Qt app it should also
> run on Windows and Linux (shortcuts are then shown with Ctrl instead of ⌘),
> but that hasn't been tested yet.

---

## Quick start

**Check whether a WF-net is sound**

1. **File ▸ New Petri Net** (⌘N).
2. Pick **Place** and click on the canvas. Type a name and press Return, and
   the tool switches back to Select on its own. Do the same with
   **Transition**.
3. Pick **Arc** and drag from a place to a transition, or the other way
   round. Drag again from the same node to add more arcs.
4. Open the **Analysis** tab on the right. It shows whether the net is a
   WF-net, whether it is sound, its behavioural properties and its
   footprint. Everything updates after each edit.
5. If it isn't sound, press **Show ▶** next to a finding. The net switches to
   *Step through* and fires the counterexample, so you can see the problem
   marking.

To try this without drawing, use **File ▸ Open Example Petri Net ▸ Order
handling (unsound)**.

**Mine a log**

1. **✎ Log from notation…** (⌘L) and type `[<a,b,c,d>^3, <a,c,b,d>^2, <a,e,d>]`,
   or open a `.xes` / `.csv` file.
2. Look through the tabs: *Overview*, *Variants*, *Dotted chart*, *Process
   map*, *Footprint*.
3. On the *Discover* tab, pick an algorithm. The model opens in the sidebar
   under **MODELS**.
4. On the model's *Conformance* tab, choose a log and press **Check
   conformance**.

**Simulate a coloured net**

**File ▸ Open Coloured Petri Net…** (⇧⌘O), then *Step through* or
*Simulate*.

---

## Petri nets and WF-nets

Nets drawn as in the lectures and the book:

- **Places** are circles with black tokens inside, drawn as dots up to 5 and
  as a number above that.
- **Transitions** are boxes with their name inside. A **silent (τ)**
  transition is a black bar.
- **Arc weights** above 1 are written on the arc.
- **Names** go inside the places and transitions, which grow to fit them.
  Tick **Names outside** in the toolbar to put them underneath instead; you
  can then drag each name where you want it. Both are saved in the PNML file.

Select anything to edit it in the **Element** tab: a place's name and
tokens, whether a transition is silent, an arc's weight and direction.

**Analysis tab**

The checks follow van der Aalst's *Workflow Verification* paper, with its
definition numbers:

- **WF-net** (Definition 11): exactly one source place *i*, one sink place
  *o*, and every node on a path between them.
- **Soundness** (Definition 12):
  - (i) option to complete;
  - (ii) proper completion;
  - (iii) no dead transitions.

  Every violation comes with a firing sequence as its counterexample, and
  **Show ▶** plays it on the net.
- **Short-circuited net N̄** (Theorem 1): the net plus a transition *t\**
  from *o* back to *i*. The net is sound iff (N̄, [i]) is **live and
  bounded**; both are shown, with the transition that can't fire again and
  the marking where that happens. Safe and deadlock-free are shown too.
  **Open N̄ as a new net** draws it.
- **Structure** (§6): **free-choice**, **well-structured** (no PT- or
  TP-handles in N̄, with the two paths of a handle spelled out) and
  **S-coverable**, plus Lemma 4's quick check for transitions that need *i*
  or *o* together with another place.
- **Behavioural properties** of the net as drawn: bounded, safe,
  deadlock-free, dead transitions, live, reversible. A WF-net always stops
  in [o], so that dead marking is marked as expected.
- **Footprint:** the → ← ‖ # matrix of the net's behaviour, to compare with
  a log's footprint (α-algorithm, footprint conformance).
- **Reachability graph…**, or a coverability graph with ω when the net is
  unbounded.
- **Conformance with a log…** opens the net as a model next to your logs,
  for token replay and alignments.

| The counterexample, replayed | The footprint of the net |
|---|---|
| ![Counterexample in the token game](docs/screenshots/petri-counterexample.png) | ![Footprint of a sound net](docs/screenshots/petri-footprint.png) |

**Also on the Petri net page**

- **Step through / Simulate:** the token game, fired by hand or at random.
  With **Trace** ticked, every fired transition shows its step numbers and
  the arcs the tokens used light up, the latest step strongest.
- **Generate event log…:** plays the net out many times and opens the
  traces as a log.
- **Saving:** nets are saved as **PNML** (ProM, WoPeD and PM4Py read it), or
  as `.cpn`.
- **Opening:** a `.pnml` file opens in this editor. A model you discovered
  has **✎ Edit a copy** to bring it here.

![Renaming a transition in place](docs/screenshots/petri-editing.png)

---

## Process mining

| Log overview | Dotted chart |
|---|---|
| ![Overview](docs/screenshots/studio-overview.png) | ![Dotted chart](docs/screenshots/studio-dotted-chart.png) |

- **Logs:**
  - XES, XES.GZ and CSV (you map the columns);
  - the course's notation, e.g. `[<a,b,c,d>^3, <a,e,d>]`;
  - XES export.
- **Explore:** overview figures, variants, cases, a ProM-style **dotted
  chart**, a **process map** (directly-follows graph with frequency or
  performance), and the **footprint** matrix.
  - Dotted chart axes: actual time, time since case start, % of case
    duration, or logical order.
  - Time unit (Auto, or seconds up to years) and a grid step you can type in.
  - Colour and shape by any attribute. The default palette can be changed
    per value: right-click a value in the legend and pick its colour.
- **Discover:**
  - α-algorithm, which shows its eight steps;
  - Inductive Miner and IMf;
  - Heuristics Miner (a dependency graph).
- **Models:**
  - token game;
  - soundness and properties;
  - reachability graph;
  - PNML / PNG / SVG export.
- **Conformance:**
  - token-based replay and optimal alignments, both drawn on the model;
  - fitness, precision, generalisation and simplicity;
  - alignments per variant.
- **Compare logs:** key figures, activity and variant shares, and linked
  dotted charts, side by side.

| Process map | Discovering a model |
|---|---|
| ![Process map](docs/screenshots/studio-process-map.png) | ![Discover](docs/screenshots/studio-discover.png) |

| α-algorithm result | Conformance (alignments on the model) |
|---|---|
| ![Alpha](docs/screenshots/studio-alpha.png) | ![Conformance](docs/screenshots/studio-conformance.png) |

| Comparing two logs | Linked dotted charts of three boarding strategies |
|---|---|
| ![Comparing two logs](docs/screenshots/compare.png) | ![Linked dotted charts](docs/screenshots/compare-dotted.png) |

The app follows the system's light or dark appearance:

![Dark mode](docs/screenshots/studio-alpha-dark.png)

---

## Coloured Petri nets

A reimplementation of the modelling, simulation and analysis parts of CPN
Tools / CPN IDE, including their **CPN ML** inscription language: colour
sets, variables, functions, guards and timed tokens.

- **Edit:** places, transitions and arcs, with their inscriptions, guards,
  time delays and declarations (syntax-highlighted). Undo and redo cover
  everything.
- **Step through:** green transitions are enabled. Click one to fire it, or
  pick an exact binding in the inspector. **Back** undoes a step, and
  **Trace** highlights the path so far.
- **Simulate:** Play (1–60 firings per second) or Fast-forward. The firing
  history can be exported **as an event log** and mined straight away.
- **State space:** runs in a separate process, so it can be stopped at any
  moment. It reports dead markings, home markings, liveness and bounds.
- **Rendering:** models look the way CPN Tools and CPN IDE draw them
  (bendpoints, label positions, token bubbles), and they save back to
  `.cpn`.

| Stepping through a model | Editing an arc (handles on every bend) |
|---|---|
| ![Step through](docs/screenshots/cpn-step-through.png) | ![Arc editing](docs/screenshots/cpn-arc-editing.png) |

![State space](docs/screenshots/cpn-state-space.png)

---

## Working on the canvas

Both editors work the same way. Arcs follow the rules of CPN IDE.

| To… | Do this |
|---|---|
| Add a place / transition | Pick **Place** / **Transition**, click the canvas, type the name, press Return |
| Rename | Double-click the place or transition, or use the Element tab |
| Connect | Hover near a place or transition and drag the translucent arrow that appears onto another node. Or pick **Arc** and drag from one node to another, or click one node, then the other. Joining two places (or two transitions) is refused, with an explanation. Esc cancels. |
| Move things | Drag them. Nodes snap into line with other nodes (dashed guides show it). Drag on empty canvas to select several. |
| Bend an arc | Press anywhere on the arc and drag: that adds a bend. Drag an existing bend (a small circle) to move it. |
| Remove a bend | Drag it back into line with its neighbours |
| Slide a straight segment | Drag the bar in the middle of a horizontal or vertical segment |
| Reconnect an arc | Drag one of its ends onto another node |
| Move a label | Drag it (names can be dragged once **Names outside** is ticked) |
| Delete | Select, then ⌫ or Delete |
| Undo / redo | ⌘Z / ⇧⌘Z, or ↶ ↷ |

The tool buttons have icons, and the mouse cursor over the canvas shows the
active tool: a plain pointer for Select, a crosshair with a circle, square
or arrow for the others.

---

## Keyboard shortcuts

Shown as on a Mac. On Windows and Linux the app shows **Ctrl** where a Mac
has **⌘** (and ⌥ = Alt, ⇧ = Shift).

| Action | Shortcut |
|---|---|
| New Petri net | ⌘N |
| New coloured Petri net | ⇧⌘N |
| Open… | ⌘O |
| Open coloured Petri net… | ⇧⌘O |
| Log from notation… | ⌘L |
| Compare logs… | ⇧⌘C |
| Save / Save As | ⌘S / ⇧⌘S |
| Undo / Redo | ⌘Z / ⇧⌘Z |
| Delete selection | ⌫ |
| Step (fire one random enabled transition) | ⌘. |
| Zoom in / out / fit / 100 % | ⌘+ / ⌘− / ⌘0 / ⌥⌘0 |
| Zoom with the mouse | ⌘-scroll or pinch |
| Toggle sidebar | ⌥⌘S |
| Cancel drawing an arc | Esc |

---

## Files

| Format | Read | Write |
|---|---|---|
| Event logs: `.xes`, `.xes.gz`, `.csv` | ✓ | `.xes` |
| Petri nets: `.pnml` (with positions, weights, τ, arc bends) | ✓ | ✓ |
| CPN Tools models: `.cpn` | ✓ | ✓ |
| Pictures of nets and charts | | `.png`, `.svg` |

Example files: `examples/petri/*.pnml` (Petri nets), `examples/*.cpn`
(coloured nets) and `tests/data/` (a plane-boarding model and log from the
course).

---

## For developers

```bash
pytest -q                 # 133 tests, including GUI tests that run offscreen
cpnpy --help              # command line: check, simulate, state space, mining
```

The engines (`cpnpy.mining`, `cpnpy.ml`, `cpnpy.sim`, `cpnpy.analysis`)
have **no dependencies**, so they work in a notebook or a script:

```python
from cpnpy.mining import read_xes, inductive_miner
from cpnpy.mining.analysis import check_soundness

net = inductive_miner(read_xes("log.xes").simple_log()).net
report = check_soundness(net)
print(report.sound, report.findings)
```

[**docs/how-it-works.md**](docs/how-it-works.md) covers the architecture, the
CPN ML subset, binding search, timed nets, the state space, the file format
and the project layout.

---

## Limitations and roadmap

Plainly stated:

1. **Hierarchical CPN models don't simulate across pages yet.** Substitution
   transitions are read, drawn and saved, but their subpages are not unfolded.
2. **No CPN monitors or simulation reports**, and **no fairness
   properties** in the state space report (it says so).
3. **Colour set ranges must be integer literals**, and `subset … by pred`
   accepts every value for now.
4. **Heuristics Miner gives a dependency graph**, not a Petri net, unless the
   optional PM4Py extra is installed.
5. **Alignments are exact but unoptimised**: they can take seconds on
   heavily concurrent models. They run in the background.
6. **Plain Petri nets live on one page.**

Next up: unfolding substitution transitions, CPN monitors, and app bundles
so CPNpy starts like any other desktop app.

## Licence

MIT. See [LICENSE](LICENSE).
