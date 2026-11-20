"""Integration tests of the loader. They need the PostgreSQL database (docker compose up -d
then init-db); they are skipped otherwise. They only touch the test municipality ZZ999."""

import pytest

psycopg = pytest.importorskip("psycopg")

from roles_fonciers.config import DATABASE_URL  # noqa: E402
from roles_fonciers.loader import import_file  # noqa: E402

CODE = "ZZ999"
YEAR = 2099


def unit_xml(division, *, value="1000", extra=""):
    return (
        f"<RLUEx><RL0104><RL0104A>{division}</RL0104A><RL0104B>01</RL0104B><RL0104C>0001</RL0104C></RL0104>"
        f"<RL0401A>{YEAR - 2}-07-01</RL0401A><RL0402A>{value}</RL0402A><RL0404A>{value}</RL0404A>{extra}</RLUEx>"
    )


def write_role(directory, units, *, code=CODE, file_code=None, truncate=False):
    xml = (
        f'<?xml version="1.0" encoding="utf-8"?><RL><VERSION>2.9</VERSION>'
        f"<RLM01A>{code}</RLM01A><RLM02A>{YEAR}</RLM02A>{units}"
    )
    xml += "" if truncate else "</RL>"
    path = directory / f"RL{file_code or code}_{YEAR}.xml"
    path.write_text(xml, encoding="utf-8")
    return path


@pytest.fixture
def conn():
    try:
        connection = psycopg.connect(DATABASE_URL, autocommit=True)
        connection.execute("SELECT 1 FROM assessment_role LIMIT 1")
    except psycopg.Error as exc:
        pytest.skip(f"database not available: {exc}")
    connection.execute("DELETE FROM assessment_role WHERE municipality_code = %s", (CODE,))
    connection.execute("DELETE FROM municipality WHERE municipality_code = %s", (CODE,))
    connection.execute("INSERT INTO municipality (municipality_code, name) VALUES (%s, 'Test')", (CODE,))
    yield connection
    connection.execute("DELETE FROM assessment_role WHERE municipality_code = %s", (CODE,))
    connection.execute("DELETE FROM municipality WHERE municipality_code = %s", (CODE,))
    connection.close()


def count_units(conn):
    return conn.execute(
        "SELECT count(*) FROM assessment_unit u JOIN assessment_role r ON r.id = u.role_id "
        "WHERE r.municipality_code = %s",
        (CODE,),
    ).fetchone()[0]


def test_counts_add_up_with_rejected_and_duplicate_units(conn, tmp_path):
    units = unit_xml("0001") + unit_xml("0001") + "<RLUEx><RL0105A>1</RL0105A></RLUEx>" + unit_xml("0002")
    result = import_file(conn, write_role(tmp_path, units), 2)
    assert result.status == "loaded"
    assert (result.units_read, result.units_loaded, result.units_rejected, result.units_duplicate) == (4, 2, 1, 1)
    assert count_units(conn) == 2
    assert {i.code for i in result.issues} >= {"DUPLICATE_UNIT", "MATRICULE_INCOMPLETE"}


def test_running_twice_does_not_duplicate(conn, tmp_path):
    path = write_role(tmp_path, unit_xml("0001") + unit_xml("0002"))
    import_file(conn, path, 5000)
    import_file(conn, path, 5000)
    assert count_units(conn) == 2
    roles = conn.execute("SELECT count(*) FROM assessment_role WHERE municipality_code = %s", (CODE,)).fetchone()[0]
    assert roles == 1


def test_skip_existing_leaves_the_role_untouched(conn, tmp_path):
    import_file(conn, write_role(tmp_path, unit_xml("0001")), 5000)
    result = import_file(conn, write_role(tmp_path, unit_xml("0001") + unit_xml("0002")), 5000, skip_existing=True)
    assert result.status == "skipped"
    assert count_units(conn) == 1


def test_a_broken_file_changes_nothing(conn, tmp_path):
    import_file(conn, write_role(tmp_path, unit_xml("0001")), 5000)
    broken = write_role(tmp_path, unit_xml("0002") + unit_xml("0003") + "<RLUEx><RL0105A>", truncate=True)
    result = import_file(conn, broken, 1)  # tiny batches: some rows are already sent when the error occurs
    assert result.status == "rejected"
    assert [i.code for i in result.issues] == ["XML_INVALID"]
    assert count_units(conn) == 1  # the previous role is intact


def test_unknown_municipality_is_rejected(conn, tmp_path):
    result = import_file(conn, write_role(tmp_path, unit_xml("0001"), code="ZZ998"), 5000)
    assert result.status == "rejected"
    assert result.issues[0].code == "UNKNOWN_MUNICIPALITY"


def test_file_name_must_match_the_header(conn, tmp_path):
    result = import_file(conn, write_role(tmp_path, unit_xml("0001"), file_code="ZZ111"), 5000)
    assert result.status == "rejected"
    assert result.issues[0].code == "CODE_MISMATCH"


def test_children_are_loaded(conn, tmp_path):
    extra = (
        "<RL0101><RL0101x><RL0101Gx>MAIN</RL0101Gx></RL0101x><RL0101x><RL0101Gx>SECOND</RL0101Gx></RL0101x></RL0101>"
        "<RL0504><RL0504x><RL0504Dx>1000</RL0504Dx><RL0504Ex>I</RL0504Ex><RL0504Fx>1</RL0504Fx></RL0504x></RL0504>"
    )
    import_file(conn, write_role(tmp_path, unit_xml("0001", extra=extra)), 5000)
    addresses = conn.execute("SELECT count(*) FROM unit_address").fetchone()[0]
    assert addresses >= 2
    splits = conn.execute("SELECT split_kind, part_code FROM unit_tax_split").fetchall()
    assert ("general", "I") in splits