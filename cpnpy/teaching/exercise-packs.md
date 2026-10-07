# Writing exercise packs

An exercise pack is a folder of worksheets. Students open it in CPNpy
(*File ▸ Open Exercise Pack…*, or click an exercise in the sidebar), answer
in the boxes on each sheet, and press **Check**. Most answers are checked by
the app — often against answers it works out itself from the log, net or
transition system you give, so you do not have to.

## The folder

```
Week 3 — Discovery/
    pack.md                          title and introduction (optional)
    1 Footprints/                    chapters are just subfolders (optional)
        Exercise 1.1 First log/
            question.md              the worksheet
            log.txt                  files the exercise gives
    2 Alpha/
        Exercise 2.1 …/
```

- Any folder with a `question.md` is an exercise. Exercises and chapters are
  listed in name order, with numbers sorted as numbers.
- `pack.md` starts with `# Title`; the rest is shown on the pack's overview.
- An exercise can give **one** of each: `log.txt` (the course's notation,
  `[<a,b,c>^3, <a,c>]`), `log.xes` or `log.csv`; `net.pnml`; `ts.txt`
  (`s0 -a-> s1`, one per line or comma-separated, plus `initial: s0`). They are
  opened beside the worksheet. Other files can be referred to by name.
- Students' work is saved next to the question: `my answers.json`,
  `my answer.pnml` for a drawn net and `my notes.md` for their scratch notes. Delete them to reset an exercise; leave
  them out when you share the pack.

## The worksheet

`question.md` is ordinary Markdown, with maths between `$…$` (inline) or
`$$…$$` (display). Its first `# heading` is the exercise's title. Wherever
students should answer, put an **answer block**:

````
**a.** Give the start activities $T_I$ of $L$.

```answer
type: set
compute: alpha.T_I
hint: Which activities does a trace begin with?
```
````

The sheet is shown top to bottom with each block as an answer box, so it reads
like the paper version. Inside a block:

- `key: value` lines;
- lines starting with spaces continue the value above (for a long `solution`);
- `- [x] …` / `- [ ] …` lines are the options of a `choice`;
- `- …` lines are more accepted answers of a `text` question.

Every block can have:

| Key | Meaning |
|---|---|
| `type` | The kind of box (below). Required, except that a block with options is a `choice`. |
| `id` | A name for the answer in `my answers.json`. Default `q1`, `q2`, … by position: give ids if you will reorder questions after students started. |
| `hint` | Shown when the student asks for a hint. |
| `solution` | The model answer, shown on *Show answer* (Markdown). Without it, the right answer the app knows is shown. |

## Types of answer box

| `type` | The student… | Checked against |
|---|---|---|
| `yesno` | picks Yes or No | `answer: yes` / `no`, or `compute:` a property |
| `choice` | picks one option (or several, when several are marked `[x]`) | the `[x]` options |
| `set` | types a set: `{a, b}`, sets of sets `{s1, s3}, {s2, s3}`, or pairs `({a}, {b, d}), …` | `answer:` in the same notation, or `compute:` |
| `number` | types a number (`0.75`, `3/4`, `75%`) | `answer:` (with `tolerance:`), or `compute:` |
| `text` | types a short answer | `answer:` and any `- alternative` lines (case and spaces ignored), or a regular expression `pattern:` |
| `footprint` | fills in a matrix of → ← ‖ # | the footprint of the exercise's log, or `of: some.pnml` for a net's |
| `trace` | types a firing sequence `register, send letter` | firable in `net.pnml` (or `net: other.pnml`) and ending as `ends:` says |
| `net` | draws a Petri net in the editor beside the sheet | `answer:`, `sound:`, `fits:` (any combination) |
| `open` | writes freely | nothing: the student compares with `solution` and says how it went |

Answers are read leniently: case, spaces, `$…$`, `\{ \}` and LaTeX subscripts
(`s_1`, `s_{1}`) do not matter, and a single set may be written with or
without its braces.

### Computed answers

`compute:` works the answer out from the exercise's own files, so it stays
right if you change the log or the net:

| Of the log | Of the net (`net.pnml`, or `of: file.pnml`) | Of the transition system (`ts.txt`) |
|---|---|---|
| `activities`, `start activities`, `end activities` | `wf-net`, `sound` | `regions`, `minimal regions` |
| `alpha.T_L`, `alpha.T_I`, `alpha.T_O` | `option to complete`, `proper completion`, `no dead transitions`, `dead transitions` | `ger(e)` |
| `alpha.X_L`, `alpha.Y_L` | `bounded`, `safe`, `live`, `deadlock-free`, `reversible` | `pre-regions(e)`, `post-regions(e)` (minimal) |
| | `free-choice`, `well-structured`, `s-coverable` | `region({s1, s3})` (yes/no) |
| | `fitness` (token replay of the log) | `elementary`, `state separation`, `forward closure` |

### Nets

```answer
type: net
start: net.pnml        # start from this net (default: the exercise's net.pnml, else empty)
answer: answer.pnml    # same complete traces as this net (or: alpha, inductive)
sound: yes             # must be a sound WF-net
fits: log              # must replay every trace of the log
```

`answer:` compares *behaviour*, not drawings: the student's net is right when it
allows exactly the same complete traces (silent steps ignored, transitions
matched by label). When it is not, the student sees the shortest traces that
differ and can replay them in the token game. `answer: alpha` compares with the
net the α-algorithm discovers from the exercise's log.

### Traces

`ends:` is one of `any` (just firable), `final` (ends in the final marking),
`deadlock` (nothing enabled, case not completed), `stuck` (the final marking can
no longer be reached) or `improper` (a token in the sink with others left
behind).

## Hiding results

While students work on an exercise, everything that would give answers away —
soundness and the other analysis results, footprints, discovered models,
conformance figures, regions — is hidden in the materials beside the sheet,
with a *Reveal* button on each.

## Checking a pack

Before sharing a pack, check it from a terminal:

```
cpnpy exercises check "Week 3 — Discovery"
```

It lists every exercise and answer box, works out every computed answer, and
reports mistakes (an unknown key, a missing file, a compute it cannot do) with
their line numbers. Add `--answers` to print the right answers.

## Older exercises

An exercise without answer blocks still works. A sheet written in lettered
parts (`a.`, `b.`, … at the start of a paragraph) gets a box under each part:
the net editor for the part that asks to draw or change a net, a text box for
the others, each with the same part of `answer.md` (`**a.** …`) as its model
answer. Otherwise, with an `answer.pnml` the student draws a net that is
compared with it, and with only an `answer.md` that file is the worked answer.
