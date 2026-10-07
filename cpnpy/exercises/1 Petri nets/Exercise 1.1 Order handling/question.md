# Exercise 1.1 — Order handling

A web shop handles each order as follows.

1. The order is received (**receive**).
2. Then the order is paid (**pay**) and shipped (**ship**). The shop does not
   wait for one before starting the other: either order, and both at the same
   time, are possible.
3. When both are done, the order is closed (**close**).

**a.** Which construct models step 2?

```answer
type: choice
- [ ] an XOR-split: after *receive*, either *pay* or *ship*
- [x] an AND-split after *receive* and an AND-join before *close*
- [ ] a loop around *pay* and *ship*
hint: Both *pay* and *ship* have to happen, in either order.
solution: An AND-split: *receive* puts a token in a place before *pay* **and**
  in one before *ship*. *close* waits for both (an AND-join), so they can
  happen in any order or at the same time.
```

**b.** Draw a **WF-net** for the process in the editor on the right. Use
exactly the transition labels in bold, and make sure your net is **sound**.
The net starts with one token in its source place $i$ and should end with one
token in its sink place $o$.

```answer
type: net
answer: answer.pnml
sound: yes
hint: Start with a place i, then receive. After receive, two places — one
  for each branch.
```

Check compares what your net *can do* with the model answer, not how it is
drawn: your layout and place names do not matter.
