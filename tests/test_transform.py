"""Tests of the transformation and validation of one property (no database needed)."""

from datetime import date
from decimal import Decimal
from pathlib import Path

from roles_fonciers.issues import IssueCollector
from roles_fonciers.transform import transform_unit
from roles_fonciers.xml_reader import RawUnit, iter_units

SAMPLE = Path(__file__).parent / "fixtures" / "RL45080_sample.xml"


def make_unit(**fields):
    base = {"RL0104A": "0103", "RL0104B": "88", "RL0104C": "5630"}
    return RawUnit(fields={**base, **fields})


def run(raw, year=2025):
    issues = IssueCollector()
    unit = transform_unit(raw, year, issues)
    return unit, {(i.severity, i.code) for i in issues.issues()}


def test_sample_is_converted_without_any_issue():
    unit, issues = run(next(iter_units(SAMPLE)))
    assert issues == set()
    v = unit.values
    assert (v["matricule_division"], v["matricule_section"], v["matricule_location"]) == ("0103", "88", "5630")
    assert v["land_value"] == Decimal("23787900")
    assert v["total_value"] == Decimal("67898200")
    assert v["market_reference_date"] == date(2023, 7, 1)
    assert v["agricultural_zoning_code"] == 2
    assert v["vacant_serviced_land"] is False
    assert v["owner_condition_code"] == 1
    assert v["neighbourhood_unit"] == "0001"  # leading zeros kept


def test_sample_children():
    unit, _ = run(next(iter_units(SAMPLE)))
    assert unit.addresses[0]["street_name"] == "PRINCIPALE"
    assert unit.owners == [{"registration_date": date(1983, 1, 1), "owner_status_code": 2}]
    assert len(unit.cadastral_refs) == 4
    assert [s["part_code"] for s in unit.tax_splits] == ["T", "B", "I"]
    assert all(s["split_kind"] == "general" for s in unit.tax_splits)
    assert unit.tax_splits[2]["law_number"] is None  # absent field stays empty


def test_zero_value_is_kept_with_a_warning():
    unit, issues = run(make_unit(RL0404A="0"))
    assert unit is not None
    assert unit.values["total_value"] == Decimal("0")  # explicit zero, not None
    assert unit.values["land_value"] is None
    assert issues == {("warning", "ZERO_OR_MISSING_VALUE")}


def test_missing_matricule_skips_the_unit():
    unit, issues = run(RawUnit(fields={"RL0104A": "0103", "RL0104B": "88"}))
    assert unit is None
    assert issues == {("error", "MATRICULE_INCOMPLETE")}


def test_code_outside_the_guide_skips_the_unit():
    unit, issues = run(make_unit(RL0303A="9", RL0404A="10"))
    assert unit is None
    assert ("error", "INVALID_CODE") in issues


def test_invalid_owner_status_skips_the_unit():
    raw = make_unit(RL0404A="10")
    raw.groups["RL0201x"] = [{"RL0201Gx": "2020-01-01", "RL0201Hx": "9"}]
    unit, issues = run(raw)
    assert unit is None
    assert ("error", "INVALID_CODE") in issues


def test_unreadable_optional_number_becomes_empty_with_a_warning():
    unit, issues = run(make_unit(RL0302A="abc", RL0404A="10"))
    assert unit is not None and unit.values["land_area_m2"] is None
    assert ("warning", "CONVERSION") in issues


def test_number_too_large_for_the_column_becomes_empty():
    unit, issues = run(make_unit(RL0306A="99999", RL0404A="10"))
    assert unit.values["number_of_floors"] is None
    assert ("warning", "CONVERSION") in issues


def test_invalid_date_becomes_empty_with_a_warning():
    unit, issues = run(make_unit(RL0401A="2023-13-45", RL0404A="10"))
    assert unit.values["market_reference_date"] is None
    assert ("warning", "CONVERSION") in issues


def test_unknown_tag_is_reported_and_the_unit_kept():
    unit, issues = run(make_unit(RL9999A="x", RL0404A="10"))
    assert unit is not None
    assert ("warning", "UNKNOWN_TAG") in issues


def test_value_mismatch_is_a_warning():
    unit, issues = run(make_unit(RL0402A="10", RL0403A="20", RL0404A="99"))
    assert unit is not None
    assert ("warning", "VALUE_MISMATCH") in issues


def test_missing_building_means_total_equals_land():
    unit, issues = run(make_unit(RL0402A="10", RL0404A="10"))
    assert "VALUE_MISMATCH" not in {code for _, code in issues}


def test_reference_date_is_checked_against_the_year():
    unit, issues = run(make_unit(RL0404A="10", RL0401A="2020-07-01"))
    assert ("warning", "REFERENCE_DATE") in issues


def test_same_problem_is_aggregated_into_one_entry():
    issues = IssueCollector()
    for i in range(50):
        issues.add("warning", "ZERO_OR_MISSING_VALUE", f"unit {i}")
    [issue] = issues.issues()
    assert issue.message.startswith("50 occurrence(s)")
    assert issue.message.count("unit") == 3  # only a few examples kept