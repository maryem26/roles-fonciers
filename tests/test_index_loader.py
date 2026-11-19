"""Tests of the index CSV parsing (no database needed)."""

import pytest

from roles_fonciers.index_loader import normalize_municipality_code, parse_index

HEADER = "code géographique,nom du territoire,lien\n"


def write_csv(tmp_path, body, *, header=HEADER, encoding="utf-8-sig"):
    path = tmp_path / "index.csv"
    path.write_text(header + body, encoding=encoding)
    return path


def test_codes_are_padded_to_five_digits(tmp_path):
    path = write_csv(tmp_path, "1023,Les Îles-de-la-Madeleine,http://x\n45080,Test,http://y\n")
    rows, problems = parse_index(path)
    assert rows == [("01023", "Les Îles-de-la-Madeleine"), ("45080", "Test")]
    assert problems == []


def test_invalid_code_is_reported_not_silently_dropped(tmp_path):
    path = write_csv(tmp_path, "ABC,Mauvais,http://x\n1042,Grosse-Île,http://y\n")
    rows, problems = parse_index(path)
    assert rows == [("01042", "Grosse-Île")]
    assert len(problems) == 1 and "ABC" in problems[0]


def test_short_line_and_duplicate_are_reported(tmp_path):
    path = write_csv(tmp_path, "7\n1023,Un,http://x\n1023,Deux,http://y\n")
    rows, problems = parse_index(path)
    assert rows == [("01023", "Un")]
    assert len(problems) == 2


def test_missing_name_keeps_the_code(tmp_path):
    path = write_csv(tmp_path, "2005,,http://x\n")
    rows, problems = parse_index(path)
    assert rows == [("02005", None)]
    assert problems == []


def test_unexpected_header_is_rejected(tmp_path):
    path = write_csv(tmp_path, "1,A,B\n", header="a,b,c\n")
    with pytest.raises(ValueError):
        parse_index(path)


def test_codes_with_letters_are_kept(tmp_path):
    path = write_csv(tmp_path, "NR020,Un territoire,http://x\nnr030,Autre,http://y\n")
    rows, problems = parse_index(path)
    assert rows == [("NR020", "Un territoire"), ("NR030", "Autre")]
    assert problems == []


@pytest.mark.parametrize("raw", ["", "ABC", "NR20", "123456", "NR-20", "٣٣٣٣٣"])
def test_invalid_codes_are_refused(raw):
    assert normalize_municipality_code(raw) is None


@pytest.mark.parametrize(
    "raw, expected", [("1023", "01023"), (" 08005 ", "08005"), ("NR942", "NR942")]
)
def test_valid_codes_are_normalized(raw, expected):
    assert normalize_municipality_code(raw) == expected