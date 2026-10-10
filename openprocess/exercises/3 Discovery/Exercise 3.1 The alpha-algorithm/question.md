# Exercise 3.1 — The α-algorithm

Consider the event log (also open on the right)

$$L = [\langle a,b,c,e \rangle^4, \langle a,c,b,e \rangle, \langle a,d,e \rangle^2]$$

**a.** Fill in the footprint matrix of $L$. Click a cell to change it; each
row is the first activity, each column the second.

```answer
type: footprint
hint: a → b when b directly follows a somewhere but never the other way
  round; ‖ when both happen; # when neither does.
```

**b.** Apply the α-algorithm. Give $T_L$, $T_I$ and $T_O$.

$T_L$ (all activities):

```answer
type: set
compute: alpha.T_L
```

$T_I$ (start activities):

```answer
type: set
compute: alpha.T_I
```

$T_O$ (end activities):

```answer
type: set
compute: alpha.T_O
```

$Y_L$, the maximal pairs $(A, B)$. Write each pair as `({a}, {b,d})`,
separated by commas.

```answer
type: set
compute: alpha.Y_L
hint: Start from X_L: pairs (A, B) with a → b for every a in A and b in B,
  and A and B each internally #. Then keep only the pairs that are not
  contained in a bigger one.
```

**c.** Draw the discovered net $\alpha(L)$ in the editor on the right: the
places $i_L$, $o_L$ and one place per pair in $Y_L$.

```answer
type: net
answer: alpha
hint: b and c are in parallel, and d is an alternative to both.
```

Can $\alpha(L)$ replay every trace of $L$?

```answer
type: yesno
answer: yes
solution: Yes: the net is sound and every trace of L fits (fitness 1).
```

The log's Footprint tab and the Discover tab are hidden until you reveal them.
