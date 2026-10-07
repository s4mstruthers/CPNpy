# Answer 2.1

**a.** Yes. It has one source place $i$, one sink place $o$, and every node
lies on a path from $i$ to $o$.

**b.** No, it is not sound. After *register*, place $c_1$ holds one token and
*send letter* and *call customer* compete for it: this is a choice (an
OR-split). But *archive* needs a token in **both** $c_2$ and $c_3$ (an
AND-join). Only one of them is ever marked.

| Condition | Holds? |
|---|---|
| (i) option to complete | no |
| (ii) proper completion | yes (no marking ever reaches $o$) |
| (iii) no dead transitions | no: *archive* is dead |

**c.** ⟨register, send letter⟩ leads to $[c_2]$, where nothing is enabled and
$[o]$ can no longer be reached (a deadlock). ⟨register, call customer⟩ gets
stuck in $[c_3]$ in the same way. *archive* can never fire.

**d.** Make the join match the split: replace $c_2$ and $c_3$ by one place $c$
that both *send letter* and *call customer* put a token in, and that
*archive* takes from. (The structural reason: the net has a PT-handle from
$c_1$ to *archive*, so it is not well-structured.)
