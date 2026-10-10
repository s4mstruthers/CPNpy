# Exercise 6.1 — Cuts and trees

Consider the event log (also open on the right)

$$L = [\langle a,b,c,d \rangle^3, \langle a,c,b,d \rangle^2, \langle a,e,d \rangle]$$

The **Inductive Miner** looks at the directly-follows graph of a log, finds a
*cut* (an operator and a partition of the activities), splits the log
accordingly, and goes on with each part until a part has one activity.

**a.** Which cut does the Inductive Miner find first for $L$? Write the
operator, then the groups in order: `→ {a} {b, c} {d}`.

```answer
type: cut
compute: im.cut
hint: Is there an activity every trace starts with, and one every trace ends
  with? Then a sequence cut separates them from the middle.
```

**b.** Give the sublog of the **second** group of that cut (the middle part),
in the course's notation.

```answer
type: log
compute: im.split(2)
hint: Project every trace on the group's activities; keep the counts.
```

**c.** Which cut does the Inductive Miner find for that sublog?

```answer
type: cut
compute: im.cut(2)
hint: In the sublog, do b and c ever occur in the same trace as e?
```

**d.** Write down the complete **process tree** the Inductive Miner
discovers, as `→(a, ×(b, c), d)` (operators →, ×, ∧, ↺; or seq, xor, and,
loop). (2 points)

```answer
type: tree
compute: im.tree
points: 2
hint: Continue cutting: b and c in the sublog are in parallel.
```

**e.** Before running it: which **transitions** will the α-algorithm's net for
$L$ have? Then run the α-algorithm box in a workflow (File ▸ New Workflow)
and compare.

```answer
type: predict
box: alpha_miner
value: net.transitions
as: set
solution: One transition per activity: {a, b, c, d, e}. The α-algorithm never
  adds silent transitions; the Inductive Miner's net may.
```

The log's Discover tab is hidden until you reveal it.
