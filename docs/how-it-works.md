# How CPNpy works

Background for anyone reading or changing the code. For *using* the app,
see the [README](../README.md).

## Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│  cpnpy.gui.studio  CPNpy Studio (process mining workspace)        │
│  cpnpy.gui         CPN editor (canvas, panels, menus)             │
├──────────────────────────────────┬───────────────────────────────┤
│  cpnpy.mining                    │  cpnpy.analysis  CPN state     │
│    log, xes, csv, stats          │                  space         │
│    dfg, footprint, layout        │  cpnpy.sim       binding +     │
│    petrinet, pnml, analysis      │                  firing rule   │
│    discovery/  alpha, inductive, │  cpnpy.io        .cpn XML      │
│                heuristics        │  cpnpy.model     CPN model     │
│    conformance/ token replay,    │  cpnpy.ml        CPN ML        │
│                alignments, quality│                               │
└──────────────────────────────────┴───────────────────────────────┘
```

Everything below the GUI has **zero runtime dependencies** — only the app
needs PySide6 — so the engines import fine in a notebook, a script or CI.
PM4Py is an *optional* extra; nothing requires it.

## The CPN ML subset

Inscriptions are written in CPN ML, a dialect of Standard ML. This
implementation has its own lexer, parser and evaluator for the practical
subset — no external SML runtime is involved.

**Supported**

- literals: `1`, `~3`, `3.14`, `"text"`, `#"c"`, `true`, `false`, `()`
- tuples `(a, b)`, lists `[a, b]` / `nil` / `::` / `^^`, records `{f = a}` and
  `#f r` / `#2 t`
- arithmetic `+ - * / div mod`, comparison `= <> < > <= >=`, `andalso`,
  `orelse`, `not`, string `^`
- `if … then … else`, `let … in … end`, `case … of … | …`, `fn … => …`
- `fun` declarations: recursive, curried, multi-clause, pattern-matched
- multisets: `` n`v ``, `++`, `--`, `empty`
- time: `@+ delay` on an arc, and a transition-level delay
- a Standard Basis subset: `List.map/filter/foldl/foldr/nth/take/drop/…`,
  `Int.toString`, `size`, `explode`, `implode`, `Math.*`
- random distributions: `discrete`, `uniform`, `exponential`, `normal`,
  `poisson`, `binomial`, `erlang`, `bernoulli`

**Colour sets** — all thirteen CPN Tools forms:

```sml
colset U   = unit;                    colset U2 = unit with e;
colset B   = bool;                    colset I  = int with 1..10;
colset II  = intinf;                  colset R  = real;
colset S   = string with "a".."z" and 1..8;
colset E   = with red | green | blue;
colset X   = index ph with 1..5;
colset P   = product A * B;
colset Rec = record name:STRING * age:INT;
colset L   = list A with 0..3;
colset Un  = union Car:CARS + Walk;
colset Sub = subset A by pred;
colset Al  = A;                       (* alias *)
```

Any of them may be declared `timed`.

**Two deliberate departures**

1. `--` truncates at zero (`max(0, a − b)`), matching CPN Tools' multiset
   difference rather than producing negative coefficients.
2. A bare value on an arc means one token: `` x `` and `` 1`x `` are the same
   thing, again as in CPN Tools.

---

## How it works

### Multisets are the whole game

A place holds a *multiset* of coloured tokens, and the firing rule is stated
entirely in multiset terms. For a transition `t` under binding `b`:

```
enabled  iff   for every input place p:   E(p,t)<b>  ≤  M(p)

firing         M'(p)  =  ( M(p) −− E(p,t)<b> )  ++  E(t,p)<b>
```

Get `≤`, `−−` and `++` right and the simulator is a short piece of code. That
is why `cpnpy/ml/multiset.py` is separate and has its own test module with
hand-computed expected values.

### Binding search is the hard part

An arc inscription `(x, n)` does not say *which* token to take. Enumerating
every variable over its colour set is correct but hopeless — three variables
over a 100-element colour set is a million candidates per transition per step.

Instead, `cpnpy/sim/binding.py` reads each input inscription as a **pattern**
and matches it against the tokens that are actually in the place, which yields
the variable values directly:

1. split `` 2`(x,n) ++ 1`y `` into *demands*: "take 2 tokens shaped `(x,n)`",
   "take 1 shaped `y`";
2. order demands so the most constrained come first;
3. satisfy them depth-first, backtracking on failure, threading a `remaining`
   multiset per place so no token is counted twice;
4. anything not a pattern (`` 1`(n+1) ``, `Chopsticks(p)`) is deferred until its
   variables are bound elsewhere, then *evaluated* and checked;
5. variables still free — ones used only in a guard or on an output arc — are
   enumerated over their colour sets;
6. finally the guard is evaluated.

If step 5 meets an infinite colour set, you get a clear error naming the
variable, not a hang.

### Timed nets

Three rules, implemented in `cpnpy/sim/simulator.py`:

- a token in a timed place carries a **time stamp**; only tokens whose stamp
  has been reached may be consumed;
- produced tokens are stamped `clock + delay`, from the arc's `@+` or the
  transition's own time inscription;
- when nothing is enabled now but some place holds a token stamped for the
  future, the clock **jumps** to the earliest such stamp.

Model time therefore moves in event-driven jumps, never in ticks. Only when no
transition is enabled *and* no future stamp exists is the model dead.

### State space

`cpnpy/analysis/state_space.py` explores breadth-first, keying the visited set
on `(marking, clock)` — markings are immutable and hashable, so this is an
ordinary Python `set`. Properties come from **Tarjan's SCC decomposition**
(written iteratively, so a hundred thousand nodes will not blow the recursion
limit):

- **dead markings** — nodes with no outgoing arcs;
- **live transitions** — those occurring inside *every* terminal SCC: whichever
  cycle the system settles into, they can still happen;
- **home markings** — if the condensed graph has exactly one terminal SCC,
  every state in it is a home marking; otherwise there are none;
- **bounds** — a direct scan for integer bounds and pointwise-maximum multiset
  bounds.

Many models have infinite state spaces, so `generate()` takes `max_nodes`.
Hitting the cap sets `partial`, and the report says so in capitals, because
properties from a partial state space are **not** proofs.

### File format

`.cpn` is XML with a `<workspaceElements>` root, a `<globbox>` of declarations
and one `<page>` per diagram. The reader (`cpnpy/io/cpn_reader.py`) is
deliberately forgiving — unknown elements are ignored, every field has a
default, and declaration text is taken from the `<layout>` element, which is
the exact source the modeller typed. Entity resolution is off, so opening a
file cannot make the process read local files or hit the network.

The writer emits the full element set CPN Tools expects, and copies sections
this implementation does not model (monitors, binders, workspace options)
verbatim from the file that was opened. So an untouched open/save is
semantically identical, an edited save keeps your monitors, and a new file gets
a minimal valid set of those sections.

---

## Project layout

```
cpnpy/
  ml/
    values.py        runtime values; hashable and totally ordered
    multiset.py      Multiset and TimedMultiset algebra
    colorsets.py     the 13 colour set forms: membership + enumeration
    lexer.py         ML tokeniser (~ negation, nesting comments, ++ / -- / @+)
    ast_nodes.py     expression, pattern and declaration nodes
    parser.py        recursive descent + precedence climbing
    evaluator.py     environments, closures, pattern matching
    builtins.py      Standard Basis subset + random distributions
    errors.py        one exception family for everything the modeller can break
  model/
    declarations.py  the colset / var / val / fun declaration compiler
    net.py           Place, Transition, Arc, Page, CPNet, Marking
  io/
    cpn_reader.py    .cpn XML -> model
    cpn_writer.py    model -> .cpn XML
  sim/
    binding.py       pattern-directed binding search
    simulator.py     the firing rule, the clock, step / run / rewind
  analysis/
    state_space.py   reachability graph, SCCs, the CPN Tools style report
  gui/
    theme.py         palette, fonts and stylesheet; light/dark aware
    items.py         Qt graphics items for places, transitions, arcs
    canvas.py        the scene, the editing tools (drag to connect, rename), the view
    arc_editing.py   CPN IDE's rules for bending, sliding and reconnecting arcs
    app.py           `cpn-ide`: CPNpy Studio opened on a new coloured net
  cli.py             the `cpnpy` command
examples/models.py   four complete models, also used as test fixtures
  mining/
    log.py           events, traces, logs, classifiers, textbook notation
    xes.py           streaming XES reader / writer (.xes, .xes.gz)
    csv_import.py    CSV logs with column mapping
    stats.py         variants, activity statistics, durations
    dfg.py           directly-follows graphs, simplification
    footprint.py     ordering relations, footprint matrix and comparison
    petrinet.py      labelled P/T nets, markings, firing rule
    pnml.py          PNML reader / writer (ProM / PM4Py compatible)
    analysis.py      reachability + coverability graphs, properties, soundness
    processtree.py   process trees and their translation to WF-nets
    layout.py        Sugiyama layered graph layout (no Graphviz needed)
    discovery/       alpha.py, inductive.py (IM, IMf), heuristics.py
    conformance/     token_replay.py, alignments.py (A*), quality.py
    pm4py_bridge.py  optional extra miners via PM4Py
  model/
    plain.py         plain Petri nets in the editor (black tokens, weights, τ)
    examples.py      example Petri nets (File ▸ Open Example Petri Net)
  gui/studio/
    app.py           window, sidebar, welcome page, dialogs, file opening
    petri_page.py    the Petri net editor with the Analysis tab
    cpn_page.py      the coloured-net editor, simulator and state space tool
    tool_icons.py    painted tool icons and cursors
    compare_page.py  logs side by side
    log_page.py      overview, variants, cases, dotted chart, map, footprint, discover
    model_page.py    canvas, token game, state space, analysis, conformance
    graph_view.py    zoomable canvas for nets, maps and state spaces
    graph_builders.py  mining objects -> canvas descriptions
    dotted_chart.py, charts.py, widgets.py, style.py, workers.py, documents.py
tests/               the test suite (tests/data holds a small course plane-boarding log)
```

---


## Using the command line

```bash
cpnpy check       model.cpn              # compile and report problems
cpnpy info        model.cpn              # colour sets, variables, initial marking
cpnpy simulate    model.cpn -n 100 --seed 7
cpnpy statespace  model.cpn --max-nodes 50000
cpnpy example     timed_conveyor -o demo.cpn
```

`--seed` makes a run reproducible: the same seed replays the same choices,
which is what makes a surprising result investigable.

---

## Using it as a library

```python
from cpnpy import read_cpn, Simulator, StateSpace

net = read_cpn("philosophers.cpn")
assert net.errors == []                  # a list of CompileIssue, empty when clean

sim = Simulator(net, seed=0)
for element in sim.all_enabled():
    print(element.describe(net))         # take <p = ph(1)>, …

sim.step()                               # fire one, chosen at random
sim.run(100)                             # or many
print(sim.marking.describe(net))

space = StateSpace(net).generate(max_nodes=20_000)
print(space.report())
print(space.dead_markings())             # [] means no deadlock
```

Building a model in code (see `examples/models.py` for four complete ones):

```python
from cpnpy import CPNet, Page, Place, Transition, Arc

net = CPNet("Demo")
net.add_declaration("colset COLOUR = with red | green;")
net.add_declaration("var c : COLOUR;")

page = net.add_page("Top")
a = Place(name="A", colour_set_name="COLOUR", initial_marking_text="1`red")
b = Place(name="B", colour_set_name="COLOUR")
t = Transition(name="move")
page.places += [a, b]
page.transitions.append(t)
page.arcs += [
    Arc(place_id=a.id, transition_id=t.id, orientation="PtoT", expression_text="c"),
    Arc(place_id=b.id, transition_id=t.id, orientation="TtoP", expression_text="c"),
]

print(net.compile())                     # [] when everything parses
```

---

