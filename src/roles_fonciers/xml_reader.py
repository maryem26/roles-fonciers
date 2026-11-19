"""Streaming reader for the assessment roll XML files.

The files can reach several hundred MB, so they are never loaded whole in
memory: each property (RLUEx element) is read, handed to the caller, then
released before the next one is read.

This module only reads. Values stay as text (zeros are kept); conversion to
numbers and dates is the job of a later step.
"""

from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

from lxml import etree

HEADER_TAGS = ("VERSION", "RLM01A", "RLM02A")
UNIT_TAG = "RLUEx"


class XmlFormatError(Exception):
    """The file cannot be read as an assessment roll. `code` goes in the issue log."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class RoleHeader:
    """The three general fields found at the start of every file (raw text)."""

    version: str
    municipality_code: str
    assessment_year: str


@dataclass
class RawUnit:
    """One property, as read from the XML.

    fields: simple tags, e.g. {"RL0104A": "0103", "RL0402A": "23787900"}.
    groups: repeatable elements, e.g. {"RL0504x": [{"RL0504Dx": "100", ...}, ...]}.
    An empty element has the value None.
    """

    fields: dict[str, str | None] = field(default_factory=dict)
    groups: dict[str, list[dict[str, str | None]]] = field(default_factory=dict)


def _is_tag(element: etree._Element) -> bool:
    """False for comments and processing instructions."""
    return isinstance(element.tag, str)


def _text(element: etree._Element) -> str | None:
    value = (element.text or "").strip()
    return value or None


def read_header(path: Path) -> RoleHeader:
    """Read VERSION, RLM01A and RLM02A, which come before the first property."""
    values: dict[str, str | None] = {}
    try:
        for event, element in etree.iterparse(str(path), events=("start", "end")):
            if not _is_tag(element):
                continue
            if event == "start" and element.tag == UNIT_TAG:
                break
            if event == "end" and element.tag in HEADER_TAGS:
                values[element.tag] = _text(element)
                if len(values) == len(HEADER_TAGS):
                    break
    except etree.XMLSyntaxError as exc:
        raise XmlFormatError("XML_INVALID", f"{path.name}: {exc}") from exc

    missing = [tag for tag in HEADER_TAGS if not values.get(tag)]
    if missing:
        raise XmlFormatError("HEADER_MISSING", f"{path.name}: missing {', '.join(missing)}")
    return RoleHeader(values["VERSION"], values["RLM01A"], values["RLM02A"])


def _read_unit(unit: etree._Element) -> RawUnit:
    raw = RawUnit()
    for child in unit:
        if not _is_tag(child):
            continue
        if len(child) == 0:  # simple tag, e.g. RL0105A
            raw.fields[child.tag] = _text(child)
            continue
        for sub in child:  # container, e.g. RL0104 or RL0504
            if not _is_tag(sub):
                continue
            if len(sub) == 0:  # leaf inside a container, e.g. RL0104A, RL0201U
                raw.fields[sub.tag] = _text(sub)
            else:  # repeatable element, e.g. RL0504x
                item = {leaf.tag: _text(leaf) for leaf in sub if _is_tag(leaf)}
                raw.groups.setdefault(sub.tag, []).append(item)
    return raw


def iter_units(path: Path) -> Iterator[RawUnit]:
    """Yield the properties of a file one at a time, in constant memory."""
    try:
        for _, element in etree.iterparse(str(path), events=("end",), tag=UNIT_TAG, huge_tree=True):
            yield _read_unit(element)
            # Release this property and the ones before it.
            element.clear()
            while element.getprevious() is not None:
                del element.getparent()[0]
    except etree.XMLSyntaxError as exc:
        raise XmlFormatError("XML_INVALID", f"{path.name}: {exc}") from exc