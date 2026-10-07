# Exercise 2.1 — Spot the flaw

The net on the right shows how an insurer handles a complaint: it is
**register**ed, then the customer is contacted either by **send letter** or
by **call customer**, and finally the complaint is **archive**d.

**a.** Is the net a WF-net?

```answer
type: yesno
compute: wf-net
solution: Yes. It has one source place $i$, one sink place $o$, and every
  node lies on a path from $i$ to $o$.
```

**b.** Is it **sound**?

```answer
type: yesno
compute: sound
```

Which of the three conditions of soundness **fail**?

```answer
type: choice
- [x] (i) option to complete
- [ ] (ii) proper completion
- [x] (iii) no dead transitions
hint: Can *archive* ever fire? Its two input places are marked by two
  different branches of a choice.
solution: After *register*, *send letter* and *call customer* compete for
  the token in $c_1$ (an XOR-split), but *archive* needs a token in **both**
  $c_2$ and $c_3$ (an AND-join). So *archive* is dead and $[o]$ can never be
  reached. Proper completion holds, because no marking ever puts a token in $o$.
```

**c.** Give a firing sequence that ends in a **deadlock**: a marking where
nothing is enabled, though the case has not completed. Write the transitions
separated by commas.

```answer
type: trace
ends: deadlock
hint: Start with register. What can happen after that, and what then?
solution: ⟨register, send letter⟩ ends in $[c_2]$, where nothing is enabled;
  ⟨register, call customer⟩ gets stuck in $[c_3]$ the same way.
```

**d.** Change the net so that it is sound and still models the description.
Your changes are saved as *my answer.pnml*; the given net stays as it was.

```answer
type: net
start: net.pnml
answer: answer.pnml
sound: yes
hint: Make the join match the split.
solution: Replace $c_2$ and $c_3$ by one place $c$ that both *send letter*
  and *call customer* put a token in, and that *archive* takes from. (The
  structural reason for the flaw: a PT-handle from $c_1$ to *archive*, so the
  net is not well-structured.)
```

Results in the net's Analysis tab are hidden until you reveal them.
