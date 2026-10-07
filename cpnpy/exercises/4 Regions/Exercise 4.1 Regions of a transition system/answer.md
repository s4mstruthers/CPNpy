# Answer 4.1

**a.** $\{s_1, s_3\}$ is a region: $a$ enters it (both $a$-steps), $c$ and $d$
exit it, $b$ and $e$ do not cross it.
$\{s_3, s_4\}$ is not: $s_0 \xrightarrow{a} s_1$ stays outside, but
$s_2 \xrightarrow{a} s_3$ enters.

**b.**

| Event | GER | Minimal pre-regions | ⋂ pre-regions |
|---|---|---|---|
| c | $\{s_3\}$ | $\{s_1, s_3\}$, $\{s_2, s_3\}$ | $\{s_3\}$ |
| e | $\{s_4, s_5\}$ | $\{s_4, s_5\}$ | $\{s_4, s_5\}$ |

**c.** Forward closure holds: for every event the pre-regions meet exactly in
its GER. State separation **fails**: $s_4$ and $s_5$ cannot be separated,
because $s_4 \xrightarrow{e} s_6$ and $s_5 \xrightarrow{e} s_6$ would cross a
region containing only one of them differently. So the transition system is
not elementary.

**d.** The six minimal regions $\{s_6\}$, $\{s_0, s_1\}$, $\{s_0, s_2\}$,
$\{s_1, s_3\}$, $\{s_2, s_3\}$ and $\{s_4, s_5\}$ become places. $a$ and $b$
are concurrent, $c$ and $d$ are a choice, and both lead to the same place
$\{s_4, s_5\}$. The reachability graph has one state for $s_4$ and $s_5$
together, so it is **not** isomorphic to the transition system. Splitting the
label $e$ (into $e_1$ after $c$ and $e_2$ after $d$) would make it elementary.
