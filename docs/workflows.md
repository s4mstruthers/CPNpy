# Workflows: boxes, how they run, and how to write your own

The workflow framework is `cpnpy.flow`. It has no Qt in it: everything
here works in a script, a notebook, a test and from `cpnpy run`, and the
app only draws it. For *using* workflows in the app, see the README; this
page is for people who write boxes, read the code, or want to know what a
`.cpnflow` file guarantees.

## Three ideas

1. **Every algorithm is a box, and every box is a plain Python function.**
   The decorator reads the function's type hints and docstring; there is no
   base class and no registration call.
2. **Every analysis is a workflow file.** A `.cpnflow` file records the
   boxes, their settings and connections, and everything needed to get the
   same numbers again: fingerprints of the input files and of the box code,
   every seed, the versions and the installed packages.
3. **Every box shows how it got there.** A box reports notes, intermediate
   values and derivation steps while it runs; the app shows them on the
   *How* tab, next to the box's *Code*.

## Writing a box

```python
# Week 5/boxes/last_two.py
from cpnpy.flow import box, EventLog, TransitionSystem
from cpnpy.mining.transition_system import transition_system_from_log
from cpnpy import flow


@box(group="Discover")
def last_two(log: EventLog, representation: str = "multiset") -> TransitionSystem:
    """A transition system whose state is the last two activities.

    representation: multiset or sequence
    """
    ts = transition_system_from_log(log.simple_log(), "prefix", representation, 2)
    flow.note(f"{len(ts.states)} states")
    return ts
```

What the decorator reads, and nothing else:

| From | Becomes |
|---|---|
| a parameter whose type is a CPNpy type (`EventLog`, `PetriNet`, `TransitionSystem`, …) | an input connection point, named after the parameter |
| `list[Scores]` | an input that takes any number of connections |
| `Table | None`, or a default of `None` | an optional input |
| the return type | the output; a `@dataclass` whose fields are CPNpy types gives several outputs (one per field) |
| `int`, `float`, `bool`, `str` with a default | a setting, the default as its value |
| `Literal["a", "b"]` | a setting that is a choice |
| `Path` | a setting that is a file in the workflow's folder |
| the docstring | the help text; a `name: text` line in it is the help of that setting |
| `@box(name=…, group=…)` | the name on the canvas and the group in the box list (default: the function's name, and *Other*) |
| `@box(needs="pandas")` | the box is listed greyed out with "needs pandas" when the module is not installed |
| `@box(heavy=True)` | the box may take minutes: the app runs it where it can be stopped |

A mistake (a setting without a default, an unknown type, a missing return
hint) raises `BoxError` with a plain message when the file is imported.
The app keeps such a file in the list, greyed out, with the reason.

The function stays a function: `last_two(my_log)` runs it, in a notebook
or a test, exactly as the app would.

### The types

`cpnpy.flow.types` re-exports the engine's types and adds the few that
only workflows need:

| Type | What it is |
|---|---|
| `EventLog`, `SimpleLog` | a log; the control-flow view (a multiset of sequences) |
| `PetriNet`, `Marking`, `ProcessTree`, `TransitionSystem`, `DFG`, `Footprint`, `Regions` | models and the structures the algorithms work on |
| `CPNet` | a coloured Petri net (a CPN Tools model) |
| `ReplayResult`, `AlignmentResult` | conformance results, per variant |
| `Scores` | named numbers about one model: one row of a Compare table |
| `Table` | anything tabular; `samples` holds the numbers behind a distribution |
| `Figure` | a picture (SVG, and PNG when there is one) |
| `Text` | a report |
| `Dataset`, `Predictions`, `Predictor` | the prediction pipeline's rows, labels and models |
| `typing.Any` | an escape hatch: a grey connection point that connects only to one of the same declared class |

`register_type(cls, key, name)` adds a type of your own.

### Reporting how (the *How* tab)

```python
from cpnpy import flow

flow.note("Split on XOR: {a, e} | {b, c}")     # one line
flow.show(dfg, "Filtered DFG")                # an intermediate value, in its own viewer
flow.steps(result.steps())                    # (title, content) rows, as the book writes them
```

Outside a running box the calls do nothing. A result object with a
`steps()` method (like `AlphaResult`) is shown without any call, and its
`warnings` become notes.

### Other libraries

`cpnpy.flow.convert` turns CPNpy types into other libraries' objects and
back, in one line, importing nothing until asked:

```python
from cpnpy.flow.convert import convert

df = convert(log, "pandas.DataFrame")      # one row per event
figure = convert(fig, Figure)               # a matplotlib figure as SVG
table = convert(df, Table)
```

Built in: `EventLog ↔ pandas.DataFrame`, `SimpleLog ↔ EventLog`,
`Table ↔ DataFrame`, `Series → Table`, `numpy.ndarray → Table`,
`matplotlib Figure → Figure`, `PetriNet ↔ PM4Py` (through PNML).
`register(source, target, function)` adds one. The runner also applies a
converter when an output is connected to an input of a convertible type.

The *Science* boxes in `cpnpy/flow/boxes/science.py` (pandas, NumPy, SciPy,
matplotlib) are written to be copied: each is a few lines around one
library call.

## Workflows in Python

```python
from cpnpy.flow import Workflow, Runner, Sweep, save, load
from cpnpy.flow.boxes.input import typed_log
from cpnpy.flow.boxes.discover import inductive_miner
from cpnpy.flow.boxes.check import check_fit

wf = Workflow("demo")
log = wf.add(typed_log, {"text": "[<a,b,c,d>^3, <a,c,b,d>^2, <a,e,d>]"})
model = wf.add(inductive_miner, {"noise": 0.2})
fit = wf.add(check_fit)
wf.connect(log, model)                 # the input is found by type
wf.connect(model, fit, "model")
wf.connect(log, fit, "log")

run = Runner().run(wf)
print(run.value(fit).metrics)          # {'fitness': 1.0, 'precision': ..., ...}
print(run.result(model).explanation.steps)
save(wf, "demo.cpnflow", run)
```

`wf.can_connect(a, b)` says whether a connection is allowed and, if not,
why in plain words (the same words the canvas shows). `wf.validate()`
lists what stops the workflow from running.

Or write the workflow as a function and record it:

```python
from cpnpy.flow import workflow, to_python

@workflow(name="demo")
def demo():
    log = typed_log(text="[<a,b,c,d>^3, <a,c,b,d>^2, <a,e,d>]")
    model = inductive_miner(log, noise=0.2)
    return check_fit(model, log)

wf = demo.workflow                      # the boxes it calls become nodes and edges
print(to_python(wf))                    # and back to source
```

Calling a box inside a recorded function makes a node instead of running
it; the function itself still runs normally when called.

### How the runner works

- **Order.** Topological, left to right on ties.
- **Keys.** Each result is kept under `sha256(box code + settings + input keys)`.
  Change a setting and only the boxes after it run again; open a workflow
  whose inputs have not changed and nothing runs; the same box with the
  same inputs anywhere is computed once (`Runner(cache=…)` shares a cache).
- **Statuses.** `waiting`, `running`, `done`, `failed` (the exception and
  its traceback are in the result), `idle` (an input is missing, or a box
  before it failed; the message says which), `blocked` (a library is
  missing or the box is not allowed to run).
- **Stopping.** `Runner.run(wf, stop=threading.Event())` checks the event
  between boxes. A `heavy` box can be run with `run_in_process`, which
  can be killed.
- **Conversions.** An output is converted to an input's type when a
  converter exists.

### Sweeps

```python
wf.set(model, noise=Sweep.parse("0..0.5 step 0.1"))     # or Sweep([0, 1, 2]) for seeds
run = Runner().run(wf)
run.variants                       # [{(node, 'noise'): 0.0}, {...: 0.1}, ...]
run.value(fit, variant=3)          # one result per value
```

The boxes after a swept setting run once per value (the cartesian product
when several are swept). A box with an input that takes any number of
connections (*Compare*, *Plot*, *Sweep table*) collects the results of
every value; every `Scores` and `Table` made under a sweep carries the
values in its `context`, which *Sweep table* turns into columns.

## The workflow file

A `.cpnflow` file is JSON:

```json
{
  "format": "cpnflow/1",
  "name": "compare discovery",
  "boxes": [{"id": "n1", "box": "cpnpy.flow.boxes.input.open_log",
             "settings": {"file": "orders.xes"}, "position": [0, 0]}, ...],
  "connections": [{"from": "n1", "output": "out", "to": "n2", "input": "log"}, ...],
  "groups": [],
  "record": {
    "versions": {"cpnpy": "0.6.0", "python": "3.12.4", "numpy": "1.26.4"},
    "environment": {"platform": "...", "packages": {"numpy": "1.26.4", ...}},
    "inputs": [{"node": "n1", "setting": "file", "file": "orders.xes", "sha256": "..."}],
    "custom_boxes": [{"file": "boxes/last_two.py", "sha256": "..."}],
    "seeds": {"n4": 0},
    "results": {"n2": "...", "n3": "..."},
    "saved": "2026-10-10T12:00:00+00:00"
  }
}
```

- `differences(record, workflow, folder)` says what has changed since the
  file was saved: an input file, a box file, a seed, the CPNpy version.
  The app shows it before *Re-run*.
- `check(workflow, record, run)` says which boxes give a different result
  than recorded (by the fingerprint of the result's content).
- `requirements_lock(record)` is a `requirements.lock` from the record's
  environment.

### Headless, and in CI

```bash
cpnpy run experiment.cpnflow                 # run it, print what every box gave
cpnpy run experiment.cpnflow --check         # re-run; exit 1 if any result differs from the record
cpnpy run experiment.cpnflow --save          # record the results in the file
cpnpy run experiment.cpnflow --sweep noise=0..0.5 step 0.1
cpnpy run experiment.cpnflow -o results/     # every result as a file (CSV, PNML, SVG)
cpnpy run experiment.cpnflow --lock          # write requirements.lock
cpnpy boxes [folder]                         # the boxes, with a folder's boxes/
cpnpy datasets list | fetch "Sepsis cases" | where
```

A paper's repository can run `cpnpy run --check` on every push; the
passing badge is the reproducibility claim.

## Public datasets

`cpnpy.flow.datasets` knows the standard logs by name (the BPI Challenge
logs, Sepsis, Road Traffic Fine Management, Hospital Billing) with where
they are published and, once fetched, their SHA-256. The *Open dataset*
box fetches a log once into `~/.cpnpy/datasets` (or `$CPNPY_DATASETS`),
checks the hash on every later use, and records the name and hash in the
workflow file. 4TU.ResearchData serves the files behind DOI pages, so the
first fetch says where to download the file by hand and where to put it;
a direct `url` can be given in `~/.cpnpy/datasets/datasets.json`, which
also takes datasets of your own.

## Where boxes come from

- `cpnpy.flow.boxes`: the standard library, one module per group.
- a folder's `boxes/` subfolder: every `.py` file, loaded with
  `library_for(folder)`; saving the file reloads the box in the app.
- installed packages that declare an entry point:

  ```toml
  [project.entry-points."cpnpy.boxes"]
  my_pack = "my_pack.boxes"
  ```

A box file runs arbitrary Python, so the app asks once before running a
folder's boxes.

## The prediction pipeline

*Prefixes* turns a log into a `Dataset` (one row per prefix, with the
next activity, the remaining time or the outcome as the label); *Split by
time* makes train and test sets by case start; *Frequency model* is a
baseline that needs no library; *Predict* applies any `Predictor`;
*Evaluate predictions* scores accuracy or MAE per prefix length. A model
of your own is a box from `Dataset` to `Predictor`:

```python
from cpnpy.flow import box, Dataset, Predictor

@box(group="Predict", needs="sklearn")
def random_forest(train: Dataset, trees: int = 100, seed: int = 0) -> Predictor:
    """A scikit-learn random forest on the prefix features."""
    from sklearn.ensemble import RandomForestClassifier, RandomForestRegressor
    cls = RandomForestClassifier if train.kind == "classification" else RandomForestRegressor
    model = cls(n_estimators=trees, random_state=seed).fit(train.X, train.y)
    model.name = f"Random forest ({trees} trees)"
    return model          # it has fit() and predict(): that is all a Predictor needs
```

(`examples/boxes/next_activity_sklearn.py` is this file.)

## Module map

```
cpnpy/flow/
  types.py      the types and their registry
  box.py        @box, BoxSpec, Port, Setting: the signature read into a box
  explain.py    flow.note / show / steps and the Explanation a run keeps
  workflow.py   Workflow, Node, Edge, Group; @workflow recording; to_python
  runner.py     Runner, Run, Result, Cache; sweeps; run_in_process
  sweep.py      Sweep and its notation
  record.py     fingerprints, the environment, the .cpnflow file, differences, check
  convert.py    converters to and from pandas, NumPy, matplotlib, PM4Py
  library.py    Library: the standard boxes, a folder's boxes/, entry points
  datasets.py   the public logs by name
  boxes/        input, filter, discover, check, compare, output, science, predict, cpn, sweeps
```
