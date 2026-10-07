# Exercise 4.1 — Regions of a transition system

The transition system (open on the right) has the transitions

$s_0 \xrightarrow{a} s_1$, $s_0 \xrightarrow{b} s_2$, $s_1 \xrightarrow{b} s_3$,
$s_2 \xrightarrow{a} s_3$, $s_3 \xrightarrow{c} s_4$, $s_3 \xrightarrow{d} s_5$,
$s_4 \xrightarrow{e} s_6$, $s_5 \xrightarrow{e} s_6$, with initial state $s_0$.

**a.** Is $\{s_1, s_3\}$ a region?

```answer
type: yesno
compute: region({s1, s3})
solution: Yes: a enters it (both a-steps), c and d exit it, b and e do not
  cross it.
```

Is $\{s_3, s_4\}$ a region?

```answer
type: yesno
compute: region({s3, s4})
solution: No: $s_0 \xrightarrow{a} s_1$ stays outside, but
  $s_2 \xrightarrow{a} s_3$ enters.
```

**b.** Give the minimal pre-regions of $c$, as sets of states separated by
commas, e.g. `{s0, s1}, {s0, s2}`.

```answer
type: set
compute: pre-regions(c)
hint: A pre-region of c is a region that c exits.
```

And the minimal pre-regions of $e$:

```answer
type: set
compute: pre-regions(e)
```

**c.** Does **forward closure** hold?

```answer
type: yesno
compute: forward closure
solution: Yes: for every event the pre-regions meet exactly in its GER.
```

Does **state separation** hold?

```answer
type: yesno
compute: state separation
solution: No: $s_4$ and $s_5$ cannot be separated, because
  $s_4 \xrightarrow{e} s_6$ and $s_5 \xrightarrow{e} s_6$ would cross a region
  containing only one of them differently.
```

**d.** Synthesise the Petri net from the minimal regions. Does its
reachability graph equal (is it isomorphic to) the transition system?

```answer
type: yesno
answer: no
solution: No. The six minimal regions become places; a and b are concurrent,
  c and d are a choice, and both lead to the same place {s4, s5}. The
  reachability graph has one state for $s_4$ and $s_5$ together. Splitting
  the label e (into e1 after c and e2 after d) would make the system
  elementary.
```

Use *Is this a region?* on the right to test your own sets of states; the
region lists and verdicts are hidden until you reveal them.
