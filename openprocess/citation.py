"""Citations: BibTeX for the app, and for the works each algorithm follows.

The reference list (:mod:`openprocess.references`) is written for people, one
line per work.  :func:`entry` turns such a line into a BibTeX entry, well
enough for a bibliography: the authors before the title, the title between
asterisks, the venue after it, the year at the end, and the DOI or URL when
the reference has one.  :func:`app_bibtex` cites the app itself, with its
version; ``CITATION.cff`` at the top of the repository says the same for
GitHub's *Cite this repository*.
"""

from __future__ import annotations

import datetime as _dt
import re
from dataclasses import dataclass, field
from pathlib import Path

from . import references as _references

APP_TITLE = "OpenProcess: process mining, Petri nets and workflows in one open app"
APP_URL = "https://github.com/s4mstruthers/openprocess"
APP_AUTHORS = (("Struthers", "Sam"),)


def app_version() -> str:
    from . import __version__
    return __version__


def concept_doi() -> str:
    """The DOI Zenodo gives the software (all versions), from ``CITATION.cff``
    at the top of the repository or installed beside the package; "" until
    the first release is archived."""
    import re
    for candidate in (Path(__file__).resolve().parents[1] / "CITATION.cff",
                      Path(__file__).resolve().parent / "CITATION.cff"):
        try:
            text = candidate.read_text(encoding="utf-8")
        except OSError:
            continue
        found = re.search(r"^doi:\s*(\S+)\s*$", text, re.M)
        if found:
            return found.group(1).strip("'\"")
    return ""


# ---------------------------------------------------------------------------
# One entry
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Entry:
    """A BibTeX entry: its kind (``article``, ``book``, …), key and fields, in order."""

    kind: str
    key: str
    fields: dict[str, str] = field(default_factory=dict)

    def bibtex(self) -> str:
        width = max((len(name) for name in self.fields), default=0)
        lines = [f"@{self.kind}{{{self.key},"]
        for name, value in self.fields.items():
            if value:
                lines.append(f"  {name.ljust(width)} = {{{_escape(value)}}},")
        lines.append("}")
        return "\n".join(lines)


def _escape(value: str) -> str:
    return value.replace("&", r"\&").replace("%", r"\%").replace("#", r"\#")


_TITLE = re.compile(r"\*(.+?)\*")
_YEAR = re.compile(r"\b(19|20)\d{2}\b")
_VOLUME = re.compile(r"\s*(\d+)\((\d+)\):(\d+[–-]\d+)")
_PAGES = re.compile(r"pp\.\s*(\d+[–-]\d+)")
_PROCEEDINGS = ("LNCS", "LNBIP", "Proceedings", "Workshop", "Conference", "Demo Track", "CEUR", "Symposium",
                "ICPM", "Models of Concurrency")


def entry(reference: _references.Reference) -> Entry:
    """The reference as a BibTeX entry (its kind guessed from the venue)."""
    text = reference.citation.strip()
    year_match = None
    for year_match in _YEAR.finditer(text):
        pass
    year = year_match.group(0) if year_match else ""
    link = reference.link or ""
    doi, url = (link, "") if link.startswith("10.") else ("", link)
    title_match = _TITLE.search(text)
    if title_match is None:                        # a standard or a tool, named in one line
        return Entry("misc", reference.key, {"title": text.rstrip("."), "year": year, "doi": doi, "url": url})
    authors = text[:title_match.start()].strip().rstrip(".,").strip()
    title = title_match.group(1).strip().rstrip(",")
    rest = text[title_match.end():].strip().lstrip(".,").strip().rstrip(".")
    rest = re.sub(r",?\s*" + re.escape(year) + r"\s*$", "", rest).strip().rstrip(",.") if year else rest
    fields: dict[str, str] = {}
    if any(ch.isdigit() for ch in authors) or " " not in authors:
        fields["organization"] = authors          # "ISO/IEC 15909-2:2011"
    else:
        fields["author"] = " and ".join(part.strip() for part in re.split(r",\s*|\s+and\s+", authors) if part.strip())
    fields["title"] = title
    lower = text.lower()
    volume = _VOLUME.search(rest)
    if "thesis" in lower:
        kind = "phdthesis"
        fields["school"] = re.sub(r"^phd thesis,?\s*", "", rest, flags=re.I)
    elif "working paper" in lower or "technical report" in lower:
        kind = "techreport"
        fields["institution"] = rest
    elif volume is not None:
        kind = "article"
        fields["journal"] = rest[:volume.start()].strip().rstrip(",")
        fields["volume"], fields["number"], fields["pages"] = volume.group(1), volume.group(2), volume.group(3)
    elif any(word in rest for word in _PROCEEDINGS):
        kind = "inproceedings"
        booktitle, publisher = rest, ""
        if ". Springer" in rest or rest.endswith("Springer"):
            booktitle, _, publisher = rest.rpartition(". ")
            publisher = publisher.strip() or "Springer"
        pages = _PAGES.search(booktitle)
        if pages:
            fields["pages"] = pages.group(1)
            booktitle = _PAGES.sub("", booktitle).strip().rstrip(",")
        fields["booktitle"] = booktitle
        fields["publisher"] = publisher
    elif "edition" in rest or rest.endswith("Press") or rest.startswith("Springer") or rest.startswith("Cambridge"):
        kind = "book"
        edition = re.search(r"(\d+)(st|nd|rd|th) edition", rest)
        if edition:
            fields["edition"] = edition.group(1)
            rest = re.sub(r",?\s*\d+(st|nd|rd|th) edition\.?\s*", " ", rest).strip().rstrip(".,")
        fields["publisher"] = rest
    else:
        kind = "misc"
        fields["howpublished"] = rest
    fields["year"] = year
    fields["doi"] = doi
    fields["url"] = url
    return Entry(kind, reference.key, fields)


def entries_for_module(module: str) -> list[Entry]:
    """The works the code in ``module`` follows (see :func:`references.topics_for_module`)."""
    seen, out = set(), []
    for topic in _references.topics_for_module(module):
        for key in topic.sources:
            reference = _references.reference(key)
            if reference is not None and key not in seen:
                seen.add(key)
                out.append(entry(reference))
    return out


# ---------------------------------------------------------------------------
# The app itself
# ---------------------------------------------------------------------------
def app_entry(version: str | None = None, year: int | None = None, doi: str | None = None) -> Entry:
    version = version or app_version()
    year = year or _dt.date.today().year
    doi = concept_doi() if doi is None else doi
    return Entry("software", "openprocess", {
        "author": " and ".join(f"{last}, {first}" for last, first in APP_AUTHORS),
        "title": APP_TITLE,
        "version": version,
        "year": str(year),
        "doi": doi,
        "url": APP_URL,
        "note": "Every algorithm shows its code and the paper it follows; every analysis keeps a record "
                "that runs again",
    })


def app_bibtex(version: str | None = None, year: int | None = None, doi: str | None = None) -> str:
    return app_entry(version, year, doi).bibtex()


def app_text(version: str | None = None, year: int | None = None, doi: str | None = None) -> str:
    """The citation in one line, as a reference list would have it."""
    version = version or app_version()
    year = year or _dt.date.today().year
    doi = concept_doi() if doi is None else doi
    authors = ", ".join(f"{first} {last}" for last, first in APP_AUTHORS)
    where = f"https://doi.org/{doi}" if doi else APP_URL
    return f"{authors}. {APP_TITLE} (version {version}) [software], {year}. {where}"


def cff_text(version: str | None = None, released: _dt.date | None = None, doi: str = "") -> str:
    """The contents of ``CITATION.cff`` (Citation File Format 1.2.0) for
    ``version``; ``doi`` is Zenodo's concept DOI once the first release is archived."""
    version = version or app_version()
    released = released or _dt.date.today()
    authors = "\n".join(f"  - family-names: {last}\n    given-names: {first}" for last, first in APP_AUTHORS)
    return (
        "cff-version: 1.2.0\n"
        "message: If you use OpenProcess in teaching or research, please cite it as below.\n"
        "type: software\n"
        f"title: {APP_TITLE}\n"
        f"version: {version}\n"
        f"date-released: {released.isoformat()}\n"
        + (f"doi: {doi}\n" if doi else "")
        + f"repository-code: {APP_URL}\n"
        f"url: {APP_URL}\n"
        "license: MIT\n"
        "keywords:\n  - process mining\n  - Petri nets\n  - workflow nets\n  - conformance checking\n"
        "  - teaching\n  - reproducible research\n"
        f"authors:\n{authors}\n"
        "abstract: >-\n"
        "  OpenProcess is a desktop app for process mining and Petri net modelling in which\n"
        "  every algorithm is a function whose code and source paper are one click away, and\n"
        "  every analysis keeps a record of its inputs, versions and seeds so that its numbers\n"
        "  can be checked again.\n"
    )


__all__ = ["Entry", "entry", "entries_for_module", "app_entry", "app_bibtex", "app_text", "cff_text",
           "APP_TITLE", "APP_URL"]
