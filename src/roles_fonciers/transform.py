"""Transform and validate one property read from the XML.

Input: a RawUnit (text values). Output: a Unit with typed values ready for the
database, or None when the property must be skipped. Problems go to an
IssueCollector with one of three outcomes:
  - the property is skipped (severity "error"): missing matricule, code outside
    the values defined by the guide;
  - the property is kept with an empty value and a warning: unreadable
    optional number or date, unknown tag;
  - the property is kept and a warning is added: suspicious values.
"""

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any

from roles_fonciers.issues import IssueCollector
from roles_fonciers.xml_reader import RawUnit

# ---------------------------------------------------------------- converters
# Each converter takes the raw text and returns a value, or raises ValueError.

SMALLINT = (-32768, 32767)
INTEGER = (-2147483648, 2147483647)


def text(raw: str) -> str:
    return raw


def integer(bounds: tuple[int, int]) -> Callable[[str], int]:
    def convert(raw: str) -> int:
        if not re.fullmatch(r"-?[0-9]+", raw):
            raise ValueError(raw)
        value = int(raw)
        if not bounds[0] <= value <= bounds[1]:
            raise ValueError(raw)
        return value

    return convert


def decimal(integer_digits: int) -> Callable[[str], Decimal]:
    limit = Decimal(10) ** integer_digits

    def convert(raw: str) -> Decimal:
        if not re.fullmatch(r"-?[0-9]+(\.[0-9]+)?", raw):
            raise ValueError(raw)
        value = Decimal(raw)
        if abs(value) >= limit:
            raise ValueError(raw)
        return value

    return convert


def iso_date(raw: str) -> date:
    if not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", raw):
        raise ValueError(raw)
    return date.fromisoformat(raw)


def boolean(raw: str) -> bool:
    if raw not in ("0", "1"):
        raise ValueError(raw)
    return raw == "1"


def int_code(allowed: set[int]) -> Callable[[str], int]:
    to_int = integer(SMALLINT)

    def convert(raw: str) -> int:
        value = to_int(raw)
        if value not in allowed:
            raise ValueError(raw)
        return value

    return convert


def str_code(allowed: set[str]) -> Callable[[str], str]:
    def convert(raw: str) -> str:
        if raw not in allowed:
            raise ValueError(raw)
        return raw

    return convert


# ---------------------------------------------------------------- field specs


@dataclass(frozen=True)
class Field:
    tag: str  # XML tag
    column: str  # database column
    convert: Callable[[str], Any] = text
    reject_if_invalid: bool = False  # True: an invalid value skips the property


NUM13 = decimal(13)  # NUMERIC(15, 2)

UNIT_FIELDS = [
    Field("RL0104A", "matricule_division"),
    Field("RL0104B", "matricule_section"),
    Field("RL0104C", "matricule_location"),
    Field("RL0104D", "matricule_check_digit"),
    Field("RL0104E", "building_number"),
    Field("RL0104F", "local_number"),
    Field("RL0104G", "utm_zone"),
    Field("RL0104H", "discriminant"),
    Field("RL0102A", "borough_number"),
    Field("RL0105A", "primary_use_code"),
    Field("RL0106A", "file_number"),
    Field("RL0107A", "neighbourhood_unit"),
    Field("RL0201U", "owner_condition_code", int_code(set(range(1, 10))), True),
    Field("RL0301A", "frontage_m", decimal(6)),
    Field("RL0302A", "land_area_m2", NUM13),
    Field("RL0303A", "agricultural_zoning_code", int_code({0, 1, 2}), True),
    Field("RL0304A", "eae_total_area_m2", NUM13),
    Field("RL0305A", "eae_agri_zone_area_m2", NUM13),
    Field("RL0314A", "eae_max_taxation_area_m2", NUM13),
    Field("RL0315A", "forest_total_area_m2", NUM13),
    Field("RL0316A", "forest_agri_zone_area_m2", NUM13),
    Field("RL0306A", "number_of_floors", integer(SMALLINT)),
    Field("RL0307A", "construction_year", integer(SMALLINT)),
    Field("RL0307B", "construction_year_kind", str_code({"R", "E"}), True),
    Field("RL0308A", "floor_area_m2", decimal(10)),
    Field("RL0309A", "physical_link_code", int_code(set(range(1, 6))), True),
    Field("RL0310A", "construction_type_code", int_code(set(range(1, 6))), True),
    Field("RL0311A", "dwelling_count", integer(INTEGER)),
    Field("RL0312A", "rental_room_count", integer(INTEGER)),
    Field("RL0313A", "non_residential_count", integer(INTEGER)),
    Field("RL0401A", "market_reference_date", iso_date),
    Field("RL0402A", "land_value", NUM13),
    Field("RL0403A", "building_value", NUM13),
    Field("RL0404A", "total_value", NUM13),
    Field("RL0405A", "previous_role_value", NUM13),
    Field("RL0501A", "vacant_serviced_land", boolean),
    Field("RL0502A", "non_residential_class"),
    Field("RL0503A", "industrial_class", integer(SMALLINT)),
]

ADDRESS_FIELDS = [
    Field("RL0101Ax", "lower_number"),
    Field("RL0101Bx", "lower_number_suffix"),
    Field("RL0101Cx", "upper_number"),
    Field("RL0101Dx", "upper_number_suffix"),
    Field("RL0101Ex", "street_type_code"),
    Field("RL0101Fx", "link_code"),
    Field("RL0101Gx", "street_name"),
    Field("RL0101Hx", "cardinal_point_code"),
    Field("RL0101Ix", "apartment_number"),
    Field("RL0101Jx", "apartment_suffix"),
]
CADASTRAL_FIELDS = [Field(f"RL0103{c}x", f"value_{c.lower()}") for c in "ABCDEF"]
OWNER_FIELDS = [
    Field("RL0201Gx", "registration_date", iso_date),
    Field("RL0201Hx", "owner_status_code", int_code({1, 2}), True),
]


def _tax_fields(prefix: str) -> list[Field]:
    return [
        Field(f"{prefix}Ax", "law_number"),
        Field(f"{prefix}Bx", "article_number"),
        Field(f"{prefix}Cx", "paragraph_number"),
        Field(f"{prefix}Dx", "amount", NUM13),
        Field(f"{prefix}Ex", "part_code", str_code({"T", "B", "I"}), True),
        Field(f"{prefix}Fx", "taxability_code", int_code({1, 2, 3}), True),
    ]


# group tag -> (attribute of Unit, fields, extra constant columns)
GROUPS: dict[str, tuple[str, list[Field], dict[str, Any]]] = {
    "RL0101x": ("addresses", ADDRESS_FIELDS, {}),
    "RL0103x": ("cadastral_refs", CADASTRAL_FIELDS, {}),
    "RL0201x": ("owners", OWNER_FIELDS, {}),
    "RL0504x": ("tax_splits", _tax_fields("RL0504"), {"split_kind": "general"}),
    "RL0507x": ("tax_splits", _tax_fields("RL0507"), {"split_kind": "school"}),
}

# Column lists, used by the loader to build the INSERT statements.
UNIT_COLUMNS = [f.column for f in UNIT_FIELDS]
ADDRESS_COLUMNS = [f.column for f in ADDRESS_FIELDS]
CADASTRAL_COLUMNS = [f.column for f in CADASTRAL_FIELDS]
OWNER_COLUMNS = [f.column for f in OWNER_FIELDS]
TAX_SPLIT_COLUMNS = ["split_kind"] + [f.column for f in GROUPS["RL0504x"][1]]

REQUIRED_TAGS = ("RL0104A", "RL0104B", "RL0104C")
KNOWN_TAGS = {f.tag for f in UNIT_FIELDS}
# Containers that are empty in the XML show up as fields with no value.
CONTAINER_TAGS = {"RL0101", "RL0103", "RL0104", "RL0201", "RL0504", "RL0507"}


@dataclass
class Unit:
    label: str  # readable matricule, for the issue log
    values: dict[str, Any]
    addresses: list[dict[str, Any]] = field(default_factory=list)
    owners: list[dict[str, Any]] = field(default_factory=list)
    cadastral_refs: list[dict[str, Any]] = field(default_factory=list)
    tax_splits: list[dict[str, Any]] = field(default_factory=list)


def _convert_fields(
    fields: list[Field], source: dict[str, str | None], label: str, issues: IssueCollector
) -> tuple[dict[str, Any], bool]:
    """Convert `source` with the given specs. Returns (row, keep)."""
    row: dict[str, Any] = {}
    keep = True
    for spec in fields:
        raw = source.get(spec.tag)
        if raw is None:
            row[spec.column] = None
            continue
        try:
            row[spec.column] = spec.convert(raw)
        except ValueError:
            row[spec.column] = None
            if spec.reject_if_invalid:
                issues.add("error", "INVALID_CODE", f"{label} {spec.tag}={raw!r}", key=spec.tag)
                keep = False
            else:
                issues.add("warning", "CONVERSION", f"{label} {spec.tag}={raw!r}", key=spec.tag)
    return row, keep


def _unknown_tags(tags, known: set[str], label: str, issues: IssueCollector) -> None:
    for tag in tags:
        if tag not in known:
            issues.add("warning", "UNKNOWN_TAG", f"{tag} (e.g. {label})", key=tag)


def transform_unit(raw: RawUnit, assessment_year: int, issues: IssueCollector) -> Unit | None:
    """Return the typed property, or None if it must be skipped."""
    parts = [raw.fields.get(tag) for tag in REQUIRED_TAGS]
    label = "-".join(p or "?" for p in parts)
    if not all(parts):
        issues.add("error", "MATRICULE_INCOMPLETE", label)
        return None

    keep = True
    unit = Unit(label=label, values={})

    present = {t for t, v in raw.fields.items() if not (v is None and t in CONTAINER_TAGS)}
    _unknown_tags(present, KNOWN_TAGS, label, issues)
    unit.values, ok = _convert_fields(UNIT_FIELDS, raw.fields, label, issues)
    keep &= ok

    _unknown_tags(raw.groups, set(GROUPS), label, issues)
    for tag, items in raw.groups.items():
        if tag not in GROUPS:
            continue
        attribute, fields, constants = GROUPS[tag]
        for item in items:
            _unknown_tags(item, {f.tag for f in fields}, label, issues)
            row, ok = _convert_fields(fields, item, label, issues)
            keep &= ok
            getattr(unit, attribute).append({**constants, **row})

    if not keep:
        return None
    _check_values(unit, assessment_year, issues)
    return unit


def _check_values(unit: Unit, assessment_year: int, issues: IssueCollector) -> None:
    """Warnings about suspicious values. The property is kept."""
    v = unit.values
    land, building, total = v["land_value"], v["building_value"], v["total_value"]
    if total is None or total == 0:
        issues.add("warning", "ZERO_OR_MISSING_VALUE", unit.label)
    if land is not None and total is not None and land + (building or 0) != total:
        issues.add("warning", "VALUE_MISMATCH", f"{unit.label} ({land} + {building} != {total})")
    reference = v["market_reference_date"]
    expected = date(assessment_year - 2, 7, 1)
    if reference is not None and reference != expected:
        issues.add("warning", "REFERENCE_DATE", f"{unit.label} ({reference}, expected {expected})")