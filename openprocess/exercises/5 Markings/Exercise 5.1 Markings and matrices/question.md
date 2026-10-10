# Exercise 5.1 — Markings and matrices

The net on the right is the repaired complaint-handling net of Exercise 2.1:
a complaint is **register**ed, the customer is contacted by **send letter**
*or* **call customer**, and the complaint is **archive**d.

**a.** Write the net down as a tuple $(P, T, F, m_0)$: its places, its
transitions, its arcs as pairs, and its initial marking. (4 points)

```answer
type: tuple
points: 4
hint: An arc from a place to a transition is the pair (place, transition);
  from a transition to a place it is (transition, place).
```

**b.** Which marking is reached by firing *register* in $[i]$?

```answer
type: marking
compute: fire(register, [i])
hint: Firing removes a token from every input place and puts one in every
  output place.
```

**c.** Give the set of **all reachable markings** of the net.

```answer
type: markings
compute: reachable
hint: Start from [i] and fire whatever is enabled, until nothing new appears.
```

**d.** Fill in the **incidence matrix** $C$: one row per place, one column per
transition, and in each cell the tokens the transition *adds* to the place
(produced minus consumed). (2 points)

```answer
type: matrix
compute: incidence
points: 2
hint: register takes the token from i (−1) and puts one in c1 (+1); every
  other cell of its column is 0.
```

**e.** Write down the **reachability graph** as a transition system: one line
per arc, `[i] -register-> [c1]`, and a line `initial: [i]`. Any state names
will do, as long as the shape is the same.

```answer
type: ts
compute: reachability graph
hint: Its states are the markings of c.; its arcs are the firings between
  them.
```

**f.** Is the net **safe** (never more than one token in a place)?

```answer
type: yesno
compute: safe
solution: Yes: every reachable marking of c. has exactly one token.
```

Everything in the net's Analysis tab is hidden until you reveal it.
