"""The definitions reference: typesetting, the generated docs page, and the
formulas filled in for a concrete net."""

from pathlib import Path

import pytest

from cpnpy.gui.studio import instances
from cpnpy.gui.studio.mathtext import name, render, render_text
from cpnpy.mining.analysis import analyse, check_soundness
from cpnpy.mining.definitions import BY_KEY, DEFINITIONS, FOR_TITLE, SECTIONS, markdown
from cpnpy.mining.petrinet import Marking
from cpnpy.model.examples import order_handling_sound, order_handling_unsound


def test_every_definition_typesets():
    sections = {key for key, _, _ in SECTIONS}
    for definition in DEFINITIONS:
        assert definition.section in sections
        assert all(key in BY_KEY for key in definition.uses)
        for formula in definition.formulas:
            assert "\\" not in render(formula), (definition.key, formula)
        for text in (definition.summary, *definition.notes):
            assert "\\" not in render_text(text)
    assert all(key in BY_KEY for key in FOR_TITLE.values())


def test_docs_page_is_up_to_date():
    """docs/definitions.md is generated: python -m cpnpy.mining.definitions > docs/definitions.md"""
    page = Path(__file__).resolve().parents[1] / "docs" / "definitions.md"
    assert page.read_text(encoding="utf-8") == markdown()


def test_mathtext_basics():
    assert render(r"\overline{N}") == "<span style='text-decoration: overline'><i>N</i></span>"
    assert render(r"x_{1}") == "<i>x</i><sub>1</sub>"
    # a subscript attaches to a relation and keeps the space after it
    assert render(r"a >_L b") == "<i>a</i> &gt;<sub><i>L</i></sub> <i>b</i>"
    assert "↛" in render(r"M \not\xrightarrow{*} [o]")
    assert render(r"\forall p \in P") == "∀<i>p</i> ∈ <i>P</i>"
    # names with braces (as mined nets have) stay intact
    assert "p({a},{b})" in render(name("p({a},{b})"))
    with pytest.raises(ValueError):
        render(r"\frobnicate{x}")


def plain(latex: str) -> str:
    import re
    html = render(latex)
    html = re.sub("<[^>]+>", "", html)
    return html.replace("&nbsp;", " ").replace("&emsp;", " ").replace("&#8201;", "")


def test_formulas_are_filled_in_for_the_net():
    report = check_soundness(order_handling_unsound())
    wf = [plain(line) for line in instances.soundness(report, "wf_net")]
    assert wf[0].startswith("i = start") and "o = end" in wf[0]
    stuck = [plain(line) for line in instances.soundness(report, "option_to_complete")]
    assert stuck[0] == "∀M: [start] →∗ M ⇒ M →∗ [end]"
    assert stuck[1] == "but [start] →σ [c4, end]"
    assert stuck[2] == "and [c4, end] ↛∗ [end]"
    # the firing sequence is spelled out on its own line, after the formulas
    assert stuck[3] == "where σ = ⟨register, check stock, check credit, reject⟩"
    left = [plain(line) for line in instances.soundness(report, "proper_completion")]
    assert "[c2, end] ≠ [end]" in left[2]
    choice = [plain(line) for line in instances.structure(report, report.graph.net,
                                                         "free_choice")]
    assert choice == ["•ship ∩ •reject = {c3} ≠ ∅",
                      "but •ship = {c3, c4} ≠ {c3} = •reject"]
    bounded = [plain(line) for line in instances.short_circuit(report, "bounded")]
    assert any("= ω" in line for line in bounded)
    theorem = plain(instances.short_circuit(report, "soundness_theorem")[0])
    assert "unbounded" in theorem and "not sound" in theorem

    sound = check_soundness(order_handling_sound())
    live = plain(instances.short_circuit(sound, "live")[0])
    assert live.startswith("∀t ∈ T ∪ {t∗} ∀M ∈ R(N, [start])")
    cover = [plain(line) for line in instances.structure(sound, sound.graph.net,
                                                        "s_coverable")]
    assert cover == ["P1 = {c1, c3, end, start}", "P2 = {c2, c4, end, start}"]

    drawn = order_handling_sound()
    drawn.initial_marking = Marking({sound.workflow.source: 1})
    props = analyse(drawn)
    dead = [plain(line) for line in instances.properties(props, "deadlock_free")]
    assert dead[1] == "∀t ∈ T: t is not enabled in [end]"
    for key in ("bounded", "safe", "dead_transition", "live", "reversible"):
        for line in instances.properties(props, key):
            assert "\\" not in render(line)
