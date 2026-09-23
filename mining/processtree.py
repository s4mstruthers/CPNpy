"""Process trees: block-structured models that are sound by construction.

A process tree (Leemans, Fahland & van der Aalst) is a tree whose leaves are
activities or τ (silent), and whose inner nodes are operators:

=========  ======  =====================================================
operator   symbol  meaning
=========  ======  =====================================================
sequence   →       execute the children in order, left to right
choice     ×       execute exactly one child (exclusive choice, XOR)
parallel   ∧       execute all children, interleaved in any order (AND)
loop       ↺       execute the first child ("do"); then, any number of
                   times, a redo child followed by the do child again
=========  ======  =====================================================

Example: ``→(a, ×(b, c), ↺(d, τ))`` means "a, then b or c, then d one or
more times".

Why the Inductive Miner produces trees rather than nets directly: every tree
translates into a *sound* workflow net, so the IM can never return a model
that deadlocks or leaves tokens behind -- unlike the α-algorithm.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from .petrinet import Marking, PetriNet


class Operator(Enum):
    SEQUENCE = "→"
    XOR = "×"
    PARALLEL = "∧"
    LOOP = "↺"


@dataclass(eq=False)
class ProcessTree:
    """A node: an operator with children, or a leaf (``label`` or τ)."""

    operator: Operator | None = None
    children: list["ProcessTree"] = field(default_factory=list)
    label: str | None = None          # leaves only; None = τ

    # -- constructors -----------------------------------------------------
    @classmethod
    def leaf(cls, label: str | None) -> "ProcessTree":
        return cls(label=label)

    @classmethod
    def tau(cls) -> "ProcessTree":
        return cls(label=None)

    @classmethod
    def node(cls, operator: Operator, children: list["ProcessTree"]) -> "ProcessTree":
        return cls(operator=operator, children=list(children))

    @property
    def is_leaf(self) -> bool:
        return self.operator is None

    @property
    def is_tau(self) -> bool:
        return self.is_leaf and self.label is None

    # -- display ----------------------------------------------------------
    def __str__(self) -> str:
        if self.is_leaf:
            return "τ" if self.label is None else self.label
        return f"{self.operator.value}(" + ", ".join(map(str, self.children)) + ")"

    __repr__ = __str__

    def pretty(self, indent: str = "") -> str:
        """Multi-line indented rendering."""
        if self.is_leaf:
            return indent + str(self)
        lines = [indent + self.operator.value]
        lines += [child.pretty(indent + "    ") for child in self.children]
        return "\n".join(lines)

    def activities(self) -> set[str]:
        if self.is_leaf:
            return set() if self.label is None else {self.label}
        return set().union(*(child.activities() for child in self.children))

    def simplified(self) -> "ProcessTree":
        """Flatten nested identical operators: →(a, →(b, c)) becomes →(a, b, c).

        Loops are not flattened -- ↺ is not associative.
        """
        if self.is_leaf:
            return self
        children = [child.simplified() for child in self.children]
        flat: list[ProcessTree] = []
        for child in children:
            if (self.operator is not Operator.LOOP and child.operator is self.operator):
                flat.extend(child.children)
            else:
                flat.append(child)
        if len(flat) == 1 and self.operator is not Operator.LOOP:
            return flat[0]
        return ProcessTree.node(self.operator, flat)


# ---------------------------------------------------------------------------
# Translation to a workflow net
# ---------------------------------------------------------------------------
def to_petri_net(tree: ProcessTree, name: str = "Process tree") -> PetriNet:
    """Translate a tree into a sound WF-net, block by block.

    Every block is built between an *entry* place and an *exit* place:

    * leaf ``a`` / τ:  entry → [a] → exit
    * ``→(C1..Cn)``:   chain the children through fresh intermediate places
    * ``×(C1..Cn)``:   every child between the same entry and exit
    * ``∧(C1..Cn)``:   a τ *split* puts a token in each child's own entry
      place; a τ *join* waits for all children's exit places
    * ``↺(do, r1..rn)``: τ from entry to a loop place ``s``; ``do`` from s to
      ``e``; each redo from ``e`` back to ``s``; τ from ``e`` to exit.  The
      extra τs keep the loop's places private, so a redo can never re-enter
      a choice made *outside* the loop.

    Afterwards, τ transitions that merely connect two private places in
    series are removed (Murata's "fusion of series places"), which keeps the
    picture readable without changing behaviour.
    """
    net = PetriNet(name)
    source = net.add_place("source", id="source")
    sink = net.add_place("sink", id="sink")

    def build(node: ProcessTree, entry, exit_) -> None:
        if node.is_leaf:
            transition = net.add_transition(node.label)
            net.add_arc(entry, transition)
            net.add_arc(transition, exit_)
        elif node.operator is Operator.SEQUENCE:
            current = entry
            for index, child in enumerate(node.children):
                following = exit_ if index == len(node.children) - 1 else net.add_place()
                build(child, current, following)
                current = following
        elif node.operator is Operator.XOR:
            for child in node.children:
                build(child, entry, exit_)
        elif node.operator is Operator.PARALLEL:
            split = net.add_transition(None, name="τ split")
            join = net.add_transition(None, name="τ join")
            net.add_arc(entry, split)
            net.add_arc(join, exit_)
            for child in node.children:
                child_entry, child_exit = net.add_place(), net.add_place()
                net.add_arc(split, child_entry)
                net.add_arc(child_exit, join)
                build(child, child_entry, child_exit)
        elif node.operator is Operator.LOOP:
            loop_start, loop_end = net.add_place(), net.add_place()
            enter = net.add_transition(None, name="τ enter")
            leave = net.add_transition(None, name="τ exit")
            net.add_arc(entry, enter)
            net.add_arc(enter, loop_start)
            net.add_arc(loop_end, leave)
            net.add_arc(leave, exit_)
            build(node.children[0], loop_start, loop_end)
            for redo in node.children[1:]:
                build(redo, loop_end, loop_start)

    build(tree, source, sink)
    net.initial_marking = Marking({source.id: 1})
    net.final_marking = Marking({sink.id: 1})
    reduce_silent_transitions(net)
    net.info["algorithm"] = "Process tree"
    return net


def reduce_silent_transitions(net: PetriNet) -> None:
    """Remove τ transitions that only connect two places in series.

    Rule (fusion of series places): if τ has exactly one input place ``p`` and
    one output place ``q``, ``p``'s only consumer is τ, and ``q``'s only
    producer is τ, then firing τ is the *only* thing a token in p can do and
    the *only* way into q -- so p and q can be merged and τ deleted without
    changing the visible behaviour.  The source and sink are never merged
    away, so the result is still a WF-net with the same markings.
    """
    changed = True
    while changed:
        changed = False
        for transition in list(net.transitions.values()):
            if not transition.silent:
                continue
            inputs, outputs = net.preset(transition.id), net.postset(transition.id)
            if len(inputs) != 1 or len(outputs) != 1:
                continue
            (p,), (q,) = inputs, outputs
            if p == q or net.postset(p) != {transition.id} or net.preset(q) != {transition.id}:
                continue
            if any(a.weight != 1 for a in net.arcs
                   if transition.id in (a.source, a.target)):
                continue
            # Keep source/sink ids stable: merge the other place into them.
            keep, drop = (q, p) if p not in ("source", "sink") else (p, q)
            if drop in ("source", "sink"):
                continue
            net.remove_transition(transition.id)
            for arc in net.arcs:
                if arc.source == drop:
                    arc.source = keep
                if arc.target == drop:
                    arc.target = keep
            net.places.pop(drop)
            net._cache = None
            changed = True
            break
