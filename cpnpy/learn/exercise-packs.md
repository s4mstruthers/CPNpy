# Writing exercise packs

An exercise pack is a folder of worksheets. Students open it in CPNpy
(*File ▸ Open Exercise Pack…*, or click an exercise in the sidebar), answer
in the boxes on each sheet, and press **Check**. Most answers are checked by
the app — often against answers it works out itself from the log, net or
transition system you give, so you do not have to.

## Making a pack, step by step

1. **Make the folder.** One folder for the pack, with a `pack.md` (its title
   and a short introduction), and one subfolder per exercise. Name them so they
   sort in order: `1 Dotted chart`, `2 Process modelling`, …
2. **Add what each exercise gives.** A log as `log.txt` in the course's notation
   (or `log.xes` / `log.csv`), a net as `net.pnml`, a transition system as
   `ts.txt`. To make a net, draw it in CPNpy (*File ▸ New Petri Net*), give it
   its initial (and final) marking, and save it into the exercise folder as
   `net.pnml`. Pictures (`.png`) go in the folder too.
3. **Write `question.md`.** The question as students would read it on paper,
   with an `answer` block wherever they should answer (see *Choosing a box*
   below). Give every block a `solution` that explains the answer, or a grading
   scheme for open questions.
4. **Check it.** Run `cpnpy exercises check "My pack" --answers` (see
   *Checking a pack*): it finds mistakes in the blocks and prints every answer
   the app works out, so you can compare them with your own.
5. **Try it.** Open the pack in CPNpy, answer a few boxes right and wrong, and
   look at what Check says. Then delete the `my answers.json`, `my answer.pnml`
   and `my notes.md` files your try left behind.
6. **Share it.** Zip the folder or put it in a shared drive. Students open it
   with *File ▸ Open Exercise Pack…*.

### Choosing a box

- One right answer from a list (true/false, "optimal / sub-optimal / not an
  alignment", "bounded with k = 1"): `choice`, or `yesno` for yes/no.
- A property of the given net, log or transition system: `yesno` or `set`
  with `compute:`, so the app works the answer out and it cannot be wrong.
- A set, a set of sets, pairs ($Y_L$, regions, dead transitions): `set`.
- A figure (fitness, costs, counts): `number`, with `tolerance:` when it is
  rounded (`tolerance: 0.00005` for four decimals).
- The footprint of the given log: `footprint`.
- "Give a firing sequence that…": `trace`.
- "Draw a net" or "correct this net": `net`, with `sound: yes` and, when the
  behaviour has one right answer, `answer:`. To have students correct a given
  net, give it as a file and `start:` from it.
- Explanations, derivations, drawings other than nets: `open`, with the
  grading scheme as `solution`. Students write in the box (or in Notes) and
  compare.

### Pictures

`![Model (a)](model-a.png)` shows a picture from the exercise folder.
Pictures wider than the worksheet are scaled to fit. A picture in a
`solution` is only shown after *Show answer*, which is the place for model
answers drawn as pictures.

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
  `my answer.pnml` for a drawn net and `my notes.md` for their scratch notes.
  Delete them to reset an exercise; leave them out when you share the pack.

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
- a comment starts with at least two spaces and `#` (one space before `#` is
  kept, since `a # b` is the α-algorithm's choice relation);
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

## Turning a past exam into a pack

- **One exercise per exam question**, in order (`1 …` to `7 …`), with the
  points in the title: `# 3 · Petri net analysis (19 points)`.
- **Recreate given nets and logs as files** rather than pictures, so students
  can play the token game and the app can compute the answers. Check that the
  computed answers agree with the grading scheme (`--answers`): when they do
  not, look at the net again — a misread arc is the usual cause, but grading
  schemes have slips too.
- **Statements to judge** ("the model is live", "transition a is dead") become
  `yesno` blocks with `compute:`. A run of questions with the same answer for
  each transition can become one `set` block (`compute: dead transitions`).
- **Multiple-choice questions** keep their options. Where the exam accepted
  two answers, mark the best one and say in the `solution` that the other was
  accepted too (or make it `open` when both are equally right).
- **Calculations** become `number` blocks for the result, and one for each
  intermediate figure worth checking (produced, consumed, missing and remaining
  tokens), so a student finds where they went wrong.
- **Modelling questions** become `net` blocks with `sound: yes`, the grading
  scheme as `solution` and the model answer as a picture in it.
- **Questions about material that is not in the pack** (a course dataset) can
  stay, with a sentence saying so and the figures they rely on.

## Older exercises

An exercise without answer blocks still works. A sheet written in lettered
parts (`a.`, `b.`, … at the start of a paragraph) gets a box under each part:
the net editor for the part that asks to draw or change a net, a text box for
the others, each with the same part of `answer.md` (`**a.** …`) as its model
answer. Otherwise, with an `answer.pnml` the student draws a net that is
compared with it, and with only an `answer.md` that file is the worked answer.
