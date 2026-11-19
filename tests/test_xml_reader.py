"""Tests of the streaming XML reader (no database needed)."""

from pathlib import Path

import pytest

from roles_fonciers.xml_reader import XmlFormatError, iter_units, read_header

SAMPLE = Path(__file__).parent / "fixtures" / "RL45080_sample.xml"


def write_xml(tmp_path, body, name="test.xml"):
    path = tmp_path / name
    path.write_text(f'<?xml version="1.0" encoding="utf-8"?>\n<RL>{body}</RL>', encoding="utf-8")
    return path


def test_header_of_sample():
    header = read_header(SAMPLE)
    assert (header.version, header.municipality_code, header.assessment_year) == ("2.9", "45080", "2025")


def test_sample_has_one_unit():
    assert len(list(iter_units(SAMPLE))) == 1


def test_leading_zeros_are_kept_as_text():
    unit = next(iter_units(SAMPLE))
    assert unit.fields["RL0104A"] == "0103"
    assert unit.fields["RL0104C"] == "5630"
    assert unit.fields["RL0107A"] == "0001"


def test_values_and_container_leaves_are_fields():
    unit = next(iter_units(SAMPLE))
    assert unit.fields["RL0402A"] == "23787900"
    assert unit.fields["RL0404A"] == "67898200"
    assert unit.fields["RL0201U"] == "1"  # leaf inside the RL0201 container


def test_repeatable_groups_are_collected():
    unit = next(iter_units(SAMPLE))
    assert len(unit.groups["RL0101x"]) == 1
    assert unit.groups["RL0101x"][0]["RL0101Gx"] == "PRINCIPALE"
    assert len(unit.groups["RL0103x"]) == 4
    assert len(unit.groups["RL0201x"]) == 1
    assert unit.groups["RL0201x"][0]["RL0201Hx"] == "2"
    assert len(unit.groups["RL0504x"]) == 3


def test_optional_fields_stay_absent_in_a_group():
    third = next(iter_units(SAMPLE)).groups["RL0504x"][2]
    assert "RL0504Ax" not in third  # absent, not an empty value
    assert third["RL0504Dx"] == "67898200"


def test_empty_element_is_none(tmp_path):
    path = write_xml(tmp_path, "<RLUEx><RL0105A/><RL0106A>  </RL0106A></RLUEx>")
    unit = next(iter_units(path))
    assert unit.fields == {"RL0105A": None, "RL0106A": None}


def test_several_units_are_read_in_order(tmp_path):
    body = "".join(f"<RLUEx><RL0104><RL0104A>{i:04d}</RL0104A></RL0104></RLUEx>" for i in range(5))
    units = list(iter_units(write_xml(tmp_path, body)))
    assert [u.fields["RL0104A"] for u in units] == ["0000", "0001", "0002", "0003", "0004"]


def test_malformed_file_is_reported(tmp_path):
    path = write_xml(tmp_path, "<VERSION>2.9</VERSION><RLUEx><RL0105A>1")
    with pytest.raises(XmlFormatError) as error:
        list(iter_units(path))
    assert error.value.code == "XML_INVALID"


def test_missing_header_is_reported(tmp_path):
    path = write_xml(tmp_path, "<VERSION>2.9</VERSION><RLUEx></RLUEx>")
    with pytest.raises(XmlFormatError) as error:
        read_header(path)
    assert error.value.code == "HEADER_MISSING"
    assert "RLM01A" in str(error.value)