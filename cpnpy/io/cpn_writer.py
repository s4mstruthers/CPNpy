"""Writer for CPN Tools ``.cpn`` files.

The goal is a file that CPN Tools 4.0 and CPN IDE will both open without
complaint, so we emit the full element set they expect -- including the
graphical attribute groups that are structurally required even when they carry
only defaults.

Round-trip policy
-----------------
Everything this implementation models (declarations, pages, places,
transitions, arcs, their inscriptions and their layout) is written from the
model objects, so edits are reflected.  Everything it does *not* model
(monitors, binders, workspace options, the hierarchy index) is copied verbatim
from the tree the file was read from, when there is one.  That combination
means:

* a file we opened and saved without editing is semantically identical;
* a file we edited keeps its monitors and workspace settings;
* a file we created from scratch gets a minimal but valid set of those
  sections.

Colour set declarations are written as ``<layout>`` text plus the minimum
structured markup CPN Tools needs to recognise the kind.  CPN Tools re-derives
its internal representation from the layout text on load, so this is the
faithful thing to write.
"""

from __future__ import annotations

import xml.etree.ElementTree as ElementTree
from pathlib import Path
from xml.dom import minidom

from ..model.net import Arc, CPNet, Graphics, Page, Place, Transition

#: The DOCTYPE CPN Tools writes.  Kept byte-identical so that tools which
#: sniff the header recognise our output.
DOCTYPE = (
    '<!DOCTYPE workspaceElements PUBLIC "-//CPN//DTD CPNXML 1.0//EN" '
    '"http://cpntools.org/DTD/6/cpn.dtd">'
)

_ID_SEQUENCE = [0]


def _fresh_id() -> str:
    """Ids for elements that need one but that the model does not track
    (annotation boxes, type labels, and so on)."""
    _ID_SEQUENCE[0] += 1
    return f"IDW{_ID_SEQUENCE[0]}"


# ---------------------------------------------------------------------------
# Attribute groups
# ---------------------------------------------------------------------------
def _add_graphics(parent: ElementTree.Element, graphics: Graphics) -> None:
    """Write the four attribute elements every graphical object carries."""
    ElementTree.SubElement(parent, "posattr", x=f"{graphics.x:.6f}", y=f"{graphics.y:.6f}")
    ElementTree.SubElement(
        parent, "fillattr", colour=graphics.fill_colour, pattern="", filled="false"
    )
    ElementTree.SubElement(
        parent, "lineattr", colour=graphics.line_colour,
        thick=str(int(graphics.line_width)), type="Solid",
    )
    ElementTree.SubElement(parent, "textattr", colour=graphics.text_colour, bold="false")


def _at(graphics: Graphics, tag: str, default_x: float, default_y: float) -> tuple[float, float]:
    """Absolute position for a node's inscription: its stored offset (or a
    default offset) added to the node's own position."""
    dx, dy = graphics.label_offsets.get(tag, (default_x, default_y))
    return graphics.x + dx, graphics.y + dy


def _add_annotation(parent: ElementTree.Element, tag: str, text: str,
                    x: float = 0.0, y: float = 0.0) -> ElementTree.Element:
    """Write an inscription element such as ``<initmark>`` or ``<cond>``.

    CPN Tools represents every inscription as a small graphical object with its
    own id, position and a ``<text>`` payload -- even an empty one, which is
    why we always emit the element rather than skipping it when the text is
    blank.
    """
    element = ElementTree.SubElement(parent, tag, id=_fresh_id())
    _add_graphics(element, Graphics(x=x, y=y))
    text_element = ElementTree.SubElement(element, "text")
    text_element.text = text
    return element


# ---------------------------------------------------------------------------
# Declarations
# ---------------------------------------------------------------------------
def _structured_colour_set(parent: ElementTree.Element, source: str) -> None:
    """Emit the minimal structured markup for a colour set declaration.

    CPN Tools reads the ``<layout>`` text authoritatively, but its parser still
    expects one of the recognised kind elements to be present.  We infer the
    kind from the declaration text -- which we know is well-formed, because the
    model compiled it -- and emit that one element.
    """
    body = source.split("=", 1)[1] if "=" in source else source
    body = body.strip().rstrip(";").strip()
    if body.endswith("timed"):
        body = body[: -len("timed")].strip()

    first_word = body.split()[0] if body.split() else "unit"
    simple = {"unit", "bool", "int", "intinf", "real", "string"}
    if first_word in simple:
        ElementTree.SubElement(parent, first_word)
    elif first_word == "with":
        enumeration = ElementTree.SubElement(parent, "enum")
        for constant in body[len("with"):].split("|"):
            identifier = ElementTree.SubElement(enumeration, "id")
            identifier.text = constant.strip()
    elif first_word in ("product", "record", "list", "union", "index", "subset"):
        ElementTree.SubElement(parent, first_word)
    else:
        ElementTree.SubElement(parent, "alias")


def _write_globbox(cpnet: ElementTree.Element, net: CPNet) -> None:
    """Write all declarations into a single block.

    CPN Tools groups declarations into named blocks purely for display.  We
    write one block called "Declarations" and keep the original ordering, which
    is what determines whether forward references resolve.
    """
    globbox = ElementTree.SubElement(cpnet, "globbox")
    block = ElementTree.SubElement(globbox, "block", id=_fresh_id())
    block_id = ElementTree.SubElement(block, "id")
    block_id.text = "Declarations"

    for name, source in net.declarations.colour_set_sources:
        colour = ElementTree.SubElement(block, "color", id=_fresh_id())
        identifier = ElementTree.SubElement(colour, "id")
        identifier.text = name
        _structured_colour_set(colour, source)
        if source.rstrip().rstrip(";").rstrip().endswith("timed"):
            ElementTree.SubElement(colour, "timed")
        layout = ElementTree.SubElement(colour, "layout")
        layout.text = source

    # Group variables that share a declaration line back together, so the file
    # reads the way the modeller wrote it.
    seen_sources: set[str] = set()
    for _name, colour_set_name, source in net.declarations.variable_sources:
        if source in seen_sources:
            continue
        seen_sources.add(source)
        variable = ElementTree.SubElement(block, "var", id=_fresh_id())
        type_element = ElementTree.SubElement(variable, "type")
        type_id = ElementTree.SubElement(type_element, "id")
        type_id.text = colour_set_name
        for name, other_colour_set, other_source in net.declarations.variable_sources:
            if other_source == source:
                identifier = ElementTree.SubElement(variable, "id")
                identifier.text = name
        layout = ElementTree.SubElement(variable, "layout")
        layout.text = source

    for source in net.declarations.ml_sources:
        ml = ElementTree.SubElement(block, "ml", id=_fresh_id())
        ml.text = source
        layout = ElementTree.SubElement(ml, "layout")
        layout.text = source

    for name, initial in net.declarations.globref_sources:
        globref = ElementTree.SubElement(block, "globref", id=_fresh_id())
        identifier = ElementTree.SubElement(globref, "id")
        identifier.text = name
        ml = ElementTree.SubElement(globref, "ml")
        ml.text = initial
        layout = ElementTree.SubElement(globref, "layout")
        layout.text = f"globref {name} = {initial};"


# ---------------------------------------------------------------------------
# Net elements
# ---------------------------------------------------------------------------
def _write_place(page_element: ElementTree.Element, place: Place) -> None:
    element = ElementTree.SubElement(page_element, "place", id=place.id)
    _add_graphics(element, place.graphics)

    text = ElementTree.SubElement(element, "text")
    text.text = place.name

    ElementTree.SubElement(
        element, "ellipse",
        w=f"{place.graphics.width:.6f}", h=f"{place.graphics.height:.6f}",
    )
    # The token and marking elements position the little circle and the count
    # that CPN Tools draws next to a marked place (offsets, kept from the file).
    offsets = place.graphics.label_offsets
    token_x, token_y = offsets.get("token", (-10.0, 0.0))
    ElementTree.SubElement(element, "token", x=f"{token_x:.6f}", y=f"{token_y:.6f}")
    marking_x, marking_y = offsets.get("marking", (0.0, 0.0))
    marking = ElementTree.SubElement(
        element, "marking", x=f"{marking_x:.6f}", y=f"{marking_y:.6f}",
        hidden="true" if place.graphics.marking_hidden else "false",
    )
    ElementTree.SubElement(
        marking, "snap", snap_id="0",
        **{"anchor.horizontal": "0", "anchor.vertical": "0"},
    )

    # Inscriptions go where they were (relative to the place, so they follow
    # it when it is moved), or at CPN Tools' usual spots for new places.
    _add_annotation(element, "type", place.colour_set_name,
                    *_at(place.graphics, "type", 30.0, -20.0))
    _add_annotation(element, "initmark", place.initial_marking_text,
                    *_at(place.graphics, "initmark", 35.0, 20.0))

    if place.port_type:
        ElementTree.SubElement(element, "port", id=_fresh_id(), type=place.port_type)
    if place.fusion_group:
        ElementTree.SubElement(
            element, "fusioninfo", id=_fresh_id(), name=place.fusion_group
        )


def _write_transition(page_element: ElementTree.Element, transition: Transition) -> None:
    element = ElementTree.SubElement(
        page_element, "trans", id=transition.id, explicit="false"
    )
    _add_graphics(element, transition.graphics)

    text = ElementTree.SubElement(element, "text")
    text.text = transition.name

    ElementTree.SubElement(
        element, "box",
        w=f"{transition.graphics.width:.6f}", h=f"{transition.graphics.height:.6f}",
    )
    ElementTree.SubElement(element, "binding", x="7.200000", y="-3.000000")

    graphics = transition.graphics
    _add_annotation(element, "cond", transition.guard_text, *_at(graphics, "cond", -40.0, 20.0))
    _add_annotation(element, "time", transition.time_text, *_at(graphics, "time", 40.0, 20.0))
    _add_annotation(element, "code", transition.code_text, *_at(graphics, "code", 40.0, -20.0))
    _add_annotation(element, "priority", transition.priority_text,
                    *_at(graphics, "priority", -40.0, -20.0))

    if transition.is_substitution:
        portsock = "".join(
            f"({socket},{port})" for socket, port in transition.port_assignments.items()
        )
        ElementTree.SubElement(
            element, "subst",
            subpage=transition.substitution_subpage or "",
            portsock=portsock,
        )


def _write_arc(page_element: ElementTree.Element, arc: Arc, order: int,
               page: Page | None = None) -> None:
    element = ElementTree.SubElement(
        page_element, "arc", id=arc.id, orientation=arc.orientation, order=str(order)
    )
    _add_graphics(element, arc.graphics)
    ElementTree.SubElement(element, "arrowattr", headsize="1.200000", currentcyckle="2")
    ElementTree.SubElement(element, "transend", idref=arc.transition_id)
    ElementTree.SubElement(element, "placeend", idref=arc.place_id)

    for serial, (x, y) in enumerate(arc.bendpoints, start=1):
        bendpoint = ElementTree.SubElement(
            element, "bendpoint", id=_fresh_id(), serial=str(serial)
        )
        _add_graphics(bendpoint, Graphics(x=x, y=y))

    # Arc inscriptions are stored as absolute positions; new arcs get theirs
    # halfway between the two nodes.
    position = arc.graphics.label_offsets.get("annot")
    if position is None and page is not None:
        place, transition = page.place(arc.place_id), page.transition(arc.transition_id)
        if place is not None and transition is not None:
            position = ((place.graphics.x + transition.graphics.x) / 2 + 8,
                        (place.graphics.y + transition.graphics.y) / 2 + 8)
    x, y = position if position is not None else (arc.graphics.x, arc.graphics.y)
    _add_annotation(element, "annot", arc.expression_text, x=x, y=y)


def _write_page(cpnet: ElementTree.Element, page: Page) -> None:
    element = ElementTree.SubElement(cpnet, "page", id=page.id)
    ElementTree.SubElement(element, "pageattr", name=page.name)
    for place in page.places:
        _write_place(element, place)
    for transition in page.transitions:
        _write_transition(element, transition)
    for order, arc in enumerate(page.arcs, start=1):
        _write_arc(element, arc, order, page)
    ElementTree.SubElement(element, "constraints")


# ---------------------------------------------------------------------------
# Sections we preserve rather than model
# ---------------------------------------------------------------------------
_PRESERVED_SECTIONS = ("instances", "options", "binders", "monitorblock", "IndexNode")


def _write_preserved(cpnet: ElementTree.Element, net: CPNet) -> None:
    """Copy sections we do not model from the original file, or emit defaults."""
    original = None
    if net.source_tree is not None:
        original = net.source_tree.find("cpnet")
        if original is None and net.source_tree.tag == "cpnet":
            original = net.source_tree

    for section in _PRESERVED_SECTIONS:
        existing = original.find(section) if original is not None else None
        if existing is not None:
            cpnet.append(existing)
            continue
        if section == "instances":
            instances = ElementTree.SubElement(cpnet, "instances")
            for page in net.pages:
                ElementTree.SubElement(
                    instances, "instance", id=_fresh_id(), page=page.id
                )
        elif section == "monitorblock":
            ElementTree.SubElement(cpnet, "monitorblock", name="Monitors")
        elif section in ("options", "binders"):
            ElementTree.SubElement(cpnet, section)


# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------
def to_xml_string(net: CPNet, pretty: bool = True) -> str:
    """Serialise a model to ``.cpn`` XML text (including the DOCTYPE)."""
    root = ElementTree.Element("workspaceElements")
    ElementTree.SubElement(
        root, "generator", tool="CPNpy", version="0.1.0", format="6"
    )
    cpnet = ElementTree.SubElement(root, "cpnet")

    _write_globbox(cpnet, net)
    for page in net.pages:
        _write_page(cpnet, page)
    _write_preserved(cpnet, net)

    raw = ElementTree.tostring(root, encoding="unicode")
    if pretty:
        # minidom's pretty printer is slow but the files are small, and a
        # readable .cpn is genuinely useful when diffing models in git.
        parsed = minidom.parseString(raw)
        raw = parsed.documentElement.toprettyxml(indent="  ")
    return f'<?xml version="1.0" encoding="iso-8859-1"?>\n{DOCTYPE}\n{raw}'


def write_cpn(net: CPNet, path: str | Path, pretty: bool = True) -> Path:
    """Save a model to disk and return the path written."""
    file_path = Path(path)
    file_path.write_text(to_xml_string(net, pretty=pretty), encoding="utf-8")
    return file_path
