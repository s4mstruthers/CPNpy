# Answer 3.1

**a.** Footprint (row activity vs column activity):

|   | a | b | c | d | e |
|---|---|---|---|---|---|
| **a** | # | → | → | → | # |
| **b** | ← | # | ‖ | # | → |
| **c** | ← | ‖ | # | # | → |
| **d** | ← | # | # | # | → |
| **e** | # | ← | ← | ← | # |

**b.**

- $T_L = \{a, b, c, d, e\}$, $T_I = \{a\}$, $T_O = \{e\}$
- $X_L$: all pairs $(A, B)$ with $A \rightarrow B$ and the members of $A$ (and
  of $B$) pairwise $\#$, e.g. $(\{a\}, \{b\})$, $(\{a\}, \{b, d\})$,
  $(\{b, d\}, \{e\})$, …
- $Y_L$ (the maximal pairs) $= \{(\{a\}, \{b, d\}), (\{a\}, \{c, d\}),
  (\{b, d\}, \{e\}), (\{c, d\}, \{e\})\}$

**c.** $\alpha(L)$ has the places $i_L$, $o_L$ and one place per pair in
$Y_L$: $b$ and $c$ are in parallel, and $d$ is an alternative to both. The
net is sound and replays every trace of $L$ (fitness 1).
