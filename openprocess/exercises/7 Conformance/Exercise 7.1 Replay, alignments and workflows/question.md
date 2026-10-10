# Exercise 7.1 — Replay, alignments and workflows

The log $L = [\langle a,b,c,d \rangle^3, \langle a,c,b,d \rangle^2, \langle
a,e,d \rangle]$ and the net $N$ (the given net on the right) are the ones
the α-algorithm gives for Exercise 6.1. Three candidate models of $L$ are in
the exercise's folder as well: *m1.pnml*, *m2.pnml* and *m3.pnml*. Open them
with *Open Folder* in the ⋯ menu if you want to look at them.

**a.** Replay every variant of $L$ on $N$ with **token-based replay**. For
each trace, fill in the tokens **p**roduced, **c**onsumed, **m**issing and
**r**emaining. Count the token put in the source place at the start and the
one taken from the sink at the end. (3 points)

```answer
type: replay
compute: replay
points: 3
hint: A trace that fits has m = 0 and r = 0, and then p = c.
```

**b.** What is the **fitness** of $L$ on $N$ (token-based)?

```answer
type: number
compute: fitness
tolerance: 0.005
hint: fitness = ½ (1 − m/c) + ½ (1 − r/p), summed over the log.
```

**c.** The trace $\langle a, b, d \rangle$ is not in $L$. Give an **optimal
alignment** of it with $N$: the log moves on the first line, the model moves
on the second, `≫` (or `>>`) where there is no move.

```answer
type: alignment
trace: a, b, d
answer: optimal
points: 2
hint: Which activity has to happen in the model between b and d? That is a
  model move: ≫ above, the activity below.
```

**d.** Rank the three candidate models *m1*, *m2* and *m3* by their fitness
on $L$, best first.

```answer
type: ranking
over: m1.pnml, m2.pnml, m3.pnml
by: fitness
hint: m2 is a plain sequence; m3 lets b, c and e replace each other.
```

**e.** Build a **workflow** in the Workflow tab on the right that discovers a
model from $L$ with the **Inductive Miner** and checks how well it fits with
**Check fit**. Its fitness should be 1. (2 points)

```answer
type: workflow
needs: inductive_miner, check_fit
result: Check fit.metrics.fitness
answer: 1
tolerance: 0.01
points: 2
hint: Drag the Inductive Miner box from Discover and Check fit from Check;
  wire the log into both, and the miner's model into Check fit.
```

The net's Conformance tab and the log's Discover tab are hidden until you
reveal them.
