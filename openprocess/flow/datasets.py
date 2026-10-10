"""Public event logs by name, with their fingerprints.

"BPI Challenge 2012" in two papers should mean the same bytes.  This module
knows the standard logs by name, with where they are published (a DOI on
4TU.ResearchData), their file name and, once fetched, their SHA-256.  The
*Open dataset* box fetches a log once into a shared cache, checks the hash,
and records the dataset's name and hash in the workflow file.

Downloading
-----------
4TU serves the files behind a DOI landing page, so this module does not
guess download addresses: :func:`fetch` looks in the cache first, then at
``url`` when the entry (or the user's own ``datasets.json``) has one, and
otherwise says where to download the file by hand and where to put it.  The
hash is recorded on first use and checked on every later one, so a file
swapped afterwards is noticed.

Add your own entries in ``~/.openprocess/datasets/datasets.json``::

    {"my log": {"file": "my_log.xes.gz", "url": "https://…", "sha256": null,
                "description": "...", "citation": "..."}}
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from ..mining.log import EventLog


@dataclass
class DatasetInfo:
    name: str
    file: str
    doi: str = ""
    url: str = ""
    sha256: str | None = None
    description: str = ""
    citation: str = ""
    size: str = ""

    @property
    def page(self) -> str:
        return f"https://doi.org/{self.doi}" if self.doi else self.url


#: The standard logs, by the name people use for them.
REGISTRY: dict[str, DatasetInfo] = {}


def _add(name, file, doi, description, citation="", size=""):
    REGISTRY[name] = DatasetInfo(name, file, doi, "", None, description, citation, size)


_add("BPI Challenge 2012", "BPI_Challenge_2012.xes.gz", "10.4121/uuid:3926db30-f712-4394-aebc-75976070e91f",
     "Loan applications at a Dutch financial institute: 13,087 cases, 262,200 events.",
     "van Dongen, B.F. (2012). BPI Challenge 2012. 4TU.ResearchData.", "29 MB")
_add("BPI Challenge 2013 incidents", "BPI_Challenge_2013_incidents.xes.gz",
     "10.4121/uuid:500573e6-accc-4b0c-9576-aa5468b10cee",
     "Volvo IT incident management: 7,554 cases, 65,533 events.",
     "Steeman, W. (2013). BPI Challenge 2013, incidents. 4TU.ResearchData.", "3 MB")
_add("BPI Challenge 2017", "BPI Challenge 2017.xes.gz", "10.4121/uuid:5f3067df-f10b-45da-b98b-86ae4c7a310b",
     "Loan applications, the 2012 process five years on: 31,509 cases, 1,202,267 events.",
     "van Dongen, B.F. (2017). BPI Challenge 2017. 4TU.ResearchData.", "70 MB")
_add("BPI Challenge 2019", "BPI_Challenge_2019.xes", "10.4121/uuid:d06aff4b-79f0-45e6-8ec8-e19730c248f1",
     "Purchase order handling at a paints and coatings company: 251,734 cases, 1,595,923 events.",
     "van Dongen, B.F. (2019). BPI Challenge 2019. 4TU.ResearchData.", "1.5 GB")
_add("BPI Challenge 2020 domestic declarations", "DomesticDeclarations.xes.gz",
     "10.4121/uuid:3f422315-ed9d-4882-891f-e180a5b4d6c9",
     "Travel expense declarations at TU/e: 10,500 cases, 56,437 events.",
     "van Dongen, B.F. (2020). BPI Challenge 2020: Domestic Declarations. 4TU.ResearchData.", "2 MB")
_add("Sepsis cases", "Sepsis Cases - Event Log.xes.gz", "10.4121/uuid:915d2bfb-7e84-49ad-a286-dc35f063a460",
     "Sepsis patients in a Dutch hospital: 1,050 cases, 15,214 events.",
     "Mannhardt, F. (2016). Sepsis Cases - Event Log. 4TU.ResearchData.", "1 MB")
_add("Road traffic fine management", "Road_Traffic_Fine_Management_Process.xes.gz",
     "10.4121/uuid:270fd440-1057-4fb9-89a9-b699b47990f5",
     "Fines by an Italian police force: 150,370 cases, 561,470 events.",
     "de Leoni, M., Mannhardt, F. (2015). Road Traffic Fine Management Process. 4TU.ResearchData.", "8 MB")
_add("Hospital billing", "Hospital Billing - Event Log.xes.gz", "10.4121/uuid:76c46b83-c930-4798-a1c9-4be94dfeb741",
     "Billing of medical services in a hospital: 100,000 cases, 451,359 events.",
     "Mannhardt, F. (2017). Hospital Billing - Event Log. 4TU.ResearchData.", "17 MB")


def cache_dir() -> Path:
    folder = os.environ.get("OPENPROCESS_DATASETS") or os.environ.get("CPNPY_DATASETS")
    if not folder:
        folder = Path.home() / ".openprocess" / "datasets"
        old = Path.home() / ".cpnpy" / "datasets"           # CPNpy, before 0.7
        if old.is_dir() and not folder.exists():
            folder = old
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def _user_entries() -> dict[str, DatasetInfo]:
    path = cache_dir() / "datasets.json"
    if not path.is_file():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return {name: DatasetInfo(name, item["file"], item.get("doi", ""), item.get("url", ""),
                              item.get("sha256"), item.get("description", ""), item.get("citation", ""),
                              item.get("size", "")) for name, item in data.items()}


def _hashes_path() -> Path:
    return cache_dir() / "hashes.json"


def recorded_hashes() -> dict[str, str]:
    path = _hashes_path()
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}


def names() -> list[str]:
    return sorted(set(REGISTRY) | set(_user_entries()))


def info(name: str) -> DatasetInfo:
    entries = {**REGISTRY, **_user_entries()}
    key = next((k for k in entries if k.lower() == name.lower()), None)
    if key is None:
        raise KeyError(f"No dataset called {name!r}. Known: " + ", ".join(names()))
    entry = entries[key]
    if entry.sha256 is None:
        entry.sha256 = recorded_hashes().get(entry.name)
    return entry


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


class DatasetMissing(FileNotFoundError):
    """The file is not in the cache and cannot be downloaded by itself."""


def fetch(name: str, downloader: Callable[[str, Path], None] | None = None) -> Path:
    """The dataset's file in the cache, downloading it if a URL is known.

    Raises :class:`DatasetMissing` with instructions when it is not there
    and there is no URL, and ``ValueError`` when the file's hash differs
    from the recorded one.
    """
    entry = info(name)
    path = cache_dir() / entry.file
    if not path.is_file():
        if not entry.url:
            raise DatasetMissing(
                f"{entry.name} is not in the cache. Download “{entry.file}” from {entry.page} "
                f"and put it in {cache_dir()}, or add a direct url for it in "
                f"{cache_dir() / 'datasets.json'}.")
        downloader = downloader or _download
        temporary = path.with_name(path.name + ".part")
        downloader(entry.url, temporary)
        temporary.replace(path)
    digest = sha256_file(path)
    if entry.sha256 and digest != entry.sha256:
        raise ValueError(f"{entry.file} does not match the recorded fingerprint "
                         f"({entry.sha256[:12]}… expected, {digest[:12]}… found). "
                         f"Delete it from {cache_dir()} to fetch it again.")
    if not entry.sha256:
        hashes = recorded_hashes()
        hashes[entry.name] = digest
        _hashes_path().write_text(json.dumps(hashes, indent=2), encoding="utf-8")
    return path


def _download(url: str, target: Path) -> None:
    with urllib.request.urlopen(url) as response, open(target, "wb") as handle:    # noqa: S310
        shutil.copyfileobj(response, handle)


def open_dataset(name: str) -> EventLog:
    """Fetch (if needed) and read the dataset as an :class:`EventLog`."""
    from ..mining.xes import read_xes
    entry = info(name)
    path = fetch(name)
    log = read_xes(path)
    log.attributes.setdefault("concept:name", entry.name)
    log.attributes["openprocess:dataset"] = entry.name
    log.attributes["openprocess:sha256"] = entry.sha256 or recorded_hashes().get(entry.name, "")
    return log


__all__ = ["REGISTRY", "DatasetInfo", "DatasetMissing", "cache_dir", "fetch", "info", "names",
           "open_dataset", "recorded_hashes"]
