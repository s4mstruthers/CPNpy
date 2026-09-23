"""Reading and writing XES, the IEEE 1849 standard format for event logs.

What an XES file looks like
---------------------------
::

    <log xes.version="1.0">
      <extension name="Concept" prefix="concept" uri="..."/>
      <global scope="event"> <string key="concept:name" value="UNKNOWN"/> </global>
      <classifier name="Event Name" keys="concept:name"/>
      <string key="concept:name" value="Random 50 passengers"/>      <- log attribute
      <trace>
        <string key="concept:name" value="2050016"/>                  <- case id
        <event>
          <string key="concept:name" value="Move in"/>
          <date   key="time:timestamp" value="3924-10-11T09:00:00+02:00"/>
          <int    key="r" value="9"/>
        </event>
        ...
      </trace>
    </log>

Every attribute element's *tag* is its type: ``string``, ``date``, ``int``,
``float``, ``boolean``, ``id``, ``list`` or ``container``.  Attributes may nest
(an attribute can carry "meta-attributes"); we keep the value and ignore the
meta-attributes, except for ``list``/``container`` where the children *are*
the value.

How the reader works
--------------------
Logs can be hundreds of megabytes, so we do not build the whole XML tree.
:func:`xml.etree.ElementTree.iterparse` streams *end* events; when a
``<trace>`` closes we convert it to a :class:`Trace` and then ``clear()`` the
element so its memory is released.  ``.xes.gz`` files are decompressed on the
fly.

Security: the standard-library expat parser does not fetch external entities,
so opening a file cannot make the program read local files or the network.
"""

from __future__ import annotations

import gzip
import io
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, BinaryIO
from xml.etree import ElementTree as ET
from xml.sax.saxutils import quoteattr

from .log import Classifier, Event, EventLog, Trace

_ATTRIBUTE_TAGS = {"string", "date", "int", "float", "boolean", "id", "list", "container"}


# ---------------------------------------------------------------------------
# Value parsing
# ---------------------------------------------------------------------------
def parse_xes_date(text: str) -> datetime:
    """Parse an XES (xs:dateTime) timestamp into an aware ``datetime``.

    ``datetime.fromisoformat`` handles most forms since Python 3.11; we
    normalise the two things older producers emit that it rejects: a trailing
    ``Z`` and fractional seconds that are not 3 or 6 digits long.
    """
    value = text.strip()
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    # Normalise fractional seconds to 6 digits.
    if "." in value:
        head, _, rest = value.partition(".")
        digits = ""
        while rest and rest[0].isdigit():
            digits, rest = digits + rest[0], rest[1:]
        value = f"{head}.{(digits + '000000')[:6]}{rest}"
    parsed = datetime.fromisoformat(value)
    # A timestamp without offset is interpreted as UTC so that all timestamps
    # in a log are comparable (mixing naive and aware datetimes raises).
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _convert(element: ET.Element) -> Any:
    """Turn one attribute element into a Python value."""
    tag = element.tag
    raw = element.get("value")
    try:
        if tag == "string" or tag == "id":
            return raw if raw is not None else ""
        if tag == "int":
            return int(raw)
        if tag == "float":
            return float(raw)
        if tag == "boolean":
            return str(raw).strip().lower() == "true"
        if tag == "date":
            return parse_xes_date(raw)
        if tag == "list":
            # A list's items live inside a <values> child (XES 2.0) or,
            # in older files, directly as children.
            holder = element.find("values")
            children = list(holder) if holder is not None else list(element)
            return [_convert(child) for child in children if child.tag in _ATTRIBUTE_TAGS]
        if tag == "container":
            return {child.get("key"): _convert(child) for child in element
                    if child.tag in _ATTRIBUTE_TAGS}
    except (TypeError, ValueError):
        # A malformed value is kept as text rather than aborting the import:
        # one bad row should not cost the user the whole log.
        return raw
    return raw


def _attributes_of(element: ET.Element) -> dict[str, Any]:
    """The direct attribute children of a log, trace or event element."""
    return {child.get("key"): _convert(child)
            for child in element if child.tag in _ATTRIBUTE_TAGS}


def _strip_namespace(tag: str) -> str:
    """Some producers put XES in an XML namespace; we only care about names."""
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------
def _open(source: str | Path | BinaryIO) -> BinaryIO:
    if hasattr(source, "read"):
        return source  # type: ignore[return-value]
    path = Path(source)
    with open(path, "rb") as handle:
        magic = handle.read(2)
    if magic == b"\x1f\x8b":  # gzip signature, whatever the extension says
        return gzip.open(path, "rb")
    return open(path, "rb")


def read_xes(source: str | Path | BinaryIO, progress=None) -> EventLog:
    """Read an XES (or gzip-compressed XES) file into an :class:`EventLog`.

    ``progress`` is an optional callable receiving the number of traces read
    so far; the GUI uses it to update a progress indicator.
    """
    log = EventLog()
    if isinstance(source, (str, Path)):
        log.source_path = str(source)

    stream = _open(source)
    try:
        # depth tracks where we are: 1 = inside <log>, 2 = inside <trace> etc.
        # We need it to tell a log-level attribute from a trace-level one.
        stack: list[str] = []
        for kind, element in ET.iterparse(stream, events=("start", "end")):
            tag = _strip_namespace(element.tag)
            if kind == "start":
                stack.append(tag)
                continue

            stack.pop()
            element.tag = tag
            parent = stack[-1] if stack else None

            if tag == "trace":
                trace = Trace(attributes=_attributes_of(element))
                for child in element:
                    if _strip_namespace(child.tag) == "event":
                        trace.events.append(Event(_attributes_of(child)))
                log.traces.append(trace)
                element.clear()  # release memory: the whole point of streaming
                if progress is not None and len(log.traces) % 500 == 0:
                    progress(len(log.traces))
            elif tag == "event" and parent == "trace":
                # Converted when the enclosing trace closes; normalise child
                # tags now so _attributes_of recognises them.
                for child in element.iter():
                    child.tag = _strip_namespace(child.tag)
            elif tag in _ATTRIBUTE_TAGS and parent in ("event", "trace", "list",
                                                        "values", "container"):
                element.tag = tag
            elif tag == "extension" and parent == "log":
                log.extensions.append(dict(element.attrib))
            elif tag == "global" and parent == "log":
                for child in element:
                    child.tag = _strip_namespace(child.tag)
                scope = element.get("scope", "event")
                target = (log.global_trace_attributes if scope == "trace"
                          else log.global_event_attributes)
                target.update(_attributes_of(element))
            elif tag == "classifier" and parent == "log":
                keys = tuple(_split_classifier_keys(element.get("keys", "")))
                if keys:
                    log.declared_classifiers.append(
                        Classifier(element.get("name") or " + ".join(keys), keys))
            elif tag in _ATTRIBUTE_TAGS and parent == "log":
                log.attributes[element.get("key")] = _convert(element)
    finally:
        if not hasattr(source, "read"):
            stream.close()

    _apply_event_defaults(log)
    return log


def _split_classifier_keys(text: str) -> list[str]:
    """Classifier keys are space-separated; keys containing spaces are quoted."""
    keys, current, quoted = [], "", False
    for char in text:
        if char == "'":
            quoted = not quoted
        elif char == " " and not quoted:
            if current:
                keys.append(current)
            current = ""
        else:
            current += char
    if current:
        keys.append(current)
    return keys


def _apply_event_defaults(log: EventLog) -> None:
    """Nothing to fill in -- globals are *declarations*, not defaults.

    The XES standard says a global attribute is guaranteed to be present on
    every event; producers that declare globals therefore already write them.
    We deliberately do **not** copy global values ("UNKNOWN", 1970-01-01) into
    events that lack them, because doing so would invent data.
    """


def read_xes_string(text: str) -> EventLog:
    """Parse XES from a string (used by tests)."""
    return read_xes(io.BytesIO(text.encode("utf-8")))


# ---------------------------------------------------------------------------
# Writing
# ---------------------------------------------------------------------------
def _format_value(key: str, value: Any, indent: str) -> str:
    """Serialise one attribute as an XES element."""
    k = quoteattr(str(key))
    if isinstance(value, bool):  # bool before int: bool is a subclass of int
        return f'{indent}<boolean key={k} value="{str(value).lower()}"/>\n'
    if isinstance(value, int):
        return f'{indent}<int key={k} value="{value}"/>\n'
    if isinstance(value, float):
        return f'{indent}<float key={k} value="{value!r}"/>\n'
    if isinstance(value, datetime):
        stamp = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        return f'{indent}<date key={k} value="{stamp.isoformat(timespec="milliseconds")}"/>\n'
    if isinstance(value, list):
        inner = "".join(_format_value(key, item, indent + "\t\t") for item in value)
        return (f"{indent}<list key={k}>\n{indent}\t<values>\n{inner}"
                f"{indent}\t</values>\n{indent}</list>\n")
    if isinstance(value, dict):
        inner = "".join(_format_value(sub, item, indent + "\t") for sub, item in value.items())
        return f"{indent}<container key={k}>\n{inner}{indent}</container>\n"
    return f"{indent}<string key={k} value={quoteattr(str(value))}/>\n"


_STANDARD_EXTENSIONS = [
    {"name": "Concept", "prefix": "concept", "uri": "http://www.xes-standard.org/concept.xesext"},
    {"name": "Time", "prefix": "time", "uri": "http://www.xes-standard.org/time.xesext"},
    {"name": "Lifecycle", "prefix": "lifecycle", "uri": "http://www.xes-standard.org/lifecycle.xesext"},
    {"name": "Organizational", "prefix": "org", "uri": "http://www.xes-standard.org/org.xesext"},
]


def xes_string(log: EventLog) -> str:
    """Serialise a log to an XES document string."""
    out = io.StringIO()
    out.write('<?xml version="1.0" encoding="UTF-8" ?>\n')
    out.write('<!-- Written by CPNpy -->\n')
    out.write('<log xes.version="1.0" xes.features="nested-attributes">\n')
    for ext in (log.extensions or _STANDARD_EXTENSIONS):
        attrs = " ".join(f"{name}={quoteattr(str(value))}" for name, value in ext.items())
        out.write(f"\t<extension {attrs}/>\n")
    for scope, values in (("trace", log.global_trace_attributes),
                          ("event", log.global_event_attributes)):
        if values:
            out.write(f'\t<global scope="{scope}">\n')
            for key, value in values.items():
                out.write(_format_value(key, value, "\t\t"))
            out.write("\t</global>\n")
    for classifier in log.declared_classifiers:
        keys = " ".join(f"'{k}'" if " " in k else k for k in classifier.keys)
        out.write(f"\t<classifier name={quoteattr(classifier.name)} keys={quoteattr(keys)}/>\n")
    for key, value in log.attributes.items():
        out.write(_format_value(key, value, "\t"))
    for trace in log.traces:
        out.write("\t<trace>\n")
        for key, value in trace.attributes.items():
            out.write(_format_value(key, value, "\t\t"))
        for event in trace.events:
            out.write("\t\t<event>\n")
            for key, value in event.attributes.items():
                out.write(_format_value(key, value, "\t\t\t"))
            out.write("\t\t</event>\n")
        out.write("\t</trace>\n")
    out.write("</log>\n")
    return out.getvalue()


def write_xes(log: EventLog, path: str | Path) -> None:
    """Write a log to ``path``; a ``.gz`` suffix produces a compressed file."""
    text = xes_string(log).encode("utf-8")
    path = Path(path)
    if path.suffix == ".gz":
        with gzip.open(path, "wb") as handle:
            handle.write(text)
    else:
        path.write_bytes(text)
