"""Load assessment roll files into PostgreSQL.

Each file is loaded in ONE transaction: it is fully loaded or not at all.
Loading a role replaces the existing one (same municipality and year), so
running an import twice never creates duplicates.
"""

import logging
import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path

import psycopg

from roles_fonciers.database import get_connection
from roles_fonciers.index_loader import normalize_municipality_code
from roles_fonciers.issues import Issue, IssueCollector
from roles_fonciers.transform import (
    ADDRESS_COLUMNS,
    CADASTRAL_COLUMNS,
    OWNER_COLUMNS,
    TAX_SPLIT_COLUMNS,
    UNIT_COLUMNS,
    Unit,
    transform_unit,
)
from roles_fonciers.xml_reader import RoleHeader, XmlFormatError, iter_units, read_header

log = logging.getLogger(__name__)

FILE_NAME = re.compile(r"^RL([0-9A-Z]{5})_", re.IGNORECASE)
KNOWN_VERSIONS = {"2.6", "2.7", "2.8", "2.9"}


class FileRejected(Exception):
    """The whole file is refused. `code` goes in the issue log."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass
class FileResult:
    file: str
    status: str = "loaded"  # "loaded", "rejected" or "skipped"
    units_read: int = 0
    units_loaded: int = 0
    units_rejected: int = 0  # refused by the validation
    units_duplicate: int = 0  # same matricule twice in the file
    issues: list[Issue] = field(default_factory=list)


def _insert_sql(table: str, columns: list[str]) -> str:
    names = ", ".join(columns)
    values = ", ".join(f"%({c})s" for c in columns)
    return f"INSERT INTO {table} ({names}) VALUES ({values})"


UNIT_SQL = (
    _insert_sql("assessment_unit", ["role_id"] + UNIT_COLUMNS)
    + " ON CONFLICT ON CONSTRAINT uq_assessment_unit DO NOTHING RETURNING id"
)
CHILD_SQL = {
    "unit_address": _insert_sql("unit_address", ["unit_id"] + ADDRESS_COLUMNS),
    "unit_owner_registration": _insert_sql("unit_owner_registration", ["unit_id"] + OWNER_COLUMNS),
    "unit_cadastral_ref": _insert_sql("unit_cadastral_ref", ["unit_id"] + CADASTRAL_COLUMNS),
    "unit_tax_split": _insert_sql("unit_tax_split", ["unit_id"] + TAX_SPLIT_COLUMNS),
}


def _check_header(conn: psycopg.Connection, path: Path, header: RoleHeader) -> tuple[str, int]:
    """Validate the header. Returns (municipality code, year) or rejects the file."""
    code = normalize_municipality_code(header.municipality_code)
    if code is None:
        raise FileRejected("HEADER_INVALID", f"{path.name}: municipality code {header.municipality_code!r}")
    if not re.fullmatch(r"[0-9]{4}", header.assessment_year):
        raise FileRejected("HEADER_INVALID", f"{path.name}: year {header.assessment_year!r}")
    match = FILE_NAME.match(path.name)
    if match and match.group(1).upper() != code:
        raise FileRejected("CODE_MISMATCH", f"{path.name}: the file name says {match.group(1)}, the header says {code}")
    known = conn.execute("SELECT 1 FROM municipality WHERE municipality_code = %s", (code,)).fetchone()
    if not known:
        raise FileRejected("UNKNOWN_MUNICIPALITY", f"{path.name}: {code} is not in the municipality table")
    return code, int(header.assessment_year)


def _flush(cur: psycopg.Cursor, role_id: int, batch: list[Unit], issues: IssueCollector) -> tuple[int, int]:
    """Insert a batch of properties and their children. Returns (loaded, duplicates)."""
    cur.executemany(UNIT_SQL, [{"role_id": role_id, **u.values} for u in batch], returning=True)
    ids: list[int | None] = []
    while True:  # one result set per property: an id, or nothing if the matricule already exists
        row = cur.fetchone()
        ids.append(row[0] if row else None)
        if not cur.nextset():
            break

    children: dict[str, list[dict]] = {table: [] for table in CHILD_SQL}
    loaded = 0
    for unit, unit_id in zip(batch, ids, strict=True):
        if unit_id is None:
            issues.add("error", "DUPLICATE_UNIT", unit.label)
            continue
        loaded += 1
        for table, rows in (
            ("unit_address", unit.addresses),
            ("unit_owner_registration", unit.owners),
            ("unit_cadastral_ref", unit.cadastral_refs),
            ("unit_tax_split", unit.tax_splits),
        ):
            children[table].extend({"unit_id": unit_id, **row} for row in rows)
    for table, rows in children.items():
        if rows:
            cur.executemany(CHILD_SQL[table], rows)
    return loaded, len(batch) - loaded


def import_file(
    conn: psycopg.Connection, path: Path, batch_size: int, *, skip_existing: bool = False
) -> FileResult:
    """Load one file. The connection must be in autocommit mode."""
    result = FileResult(path.name)
    issues = IssueCollector()
    try:
        header = read_header(path)
        code, year = _check_header(conn, path, header)
        if header.version not in KNOWN_VERSIONS:
            issues.add("warning", "UNKNOWN_VERSION", header.version)

        exists = conn.execute(
            "SELECT 1 FROM assessment_role WHERE municipality_code = %s AND assessment_year = %s", (code, year)
        ).fetchone()
        if skip_existing and exists:
            result.status = "skipped"
        else:
            with conn.transaction():  # everything below is committed together, or not at all
                conn.execute(
                    "DELETE FROM assessment_role WHERE municipality_code = %s AND assessment_year = %s",
                    (code, year),
                )
                role_id = conn.execute(
                    "INSERT INTO assessment_role (municipality_code, assessment_year, format_version, source_file)"
                    " VALUES (%s, %s, %s, %s) RETURNING id",
                    (code, year, header.version, path.name),
                ).fetchone()[0]

                batch: list[Unit] = []
                with conn.cursor() as cur:
                    for raw in iter_units(path):
                        result.units_read += 1
                        unit = transform_unit(raw, year, issues)
                        if unit is None:
                            result.units_rejected += 1
                            continue
                        batch.append(unit)
                        if len(batch) >= batch_size:
                            loaded, duplicates = _flush(cur, role_id, batch, issues)
                            result.units_loaded += loaded
                            result.units_duplicate += duplicates
                            batch = []
                    if batch:
                        loaded, duplicates = _flush(cur, role_id, batch, issues)
                        result.units_loaded += loaded
                        result.units_duplicate += duplicates

                # Final check: the counts must add up, and match the database.
                accounted = result.units_loaded + result.units_rejected + result.units_duplicate
                in_database = conn.execute(
                    "SELECT count(*) FROM assessment_unit WHERE role_id = %s", (role_id,)
                ).fetchone()[0]
                if result.units_read != accounted or in_database != result.units_loaded:
                    raise RuntimeError(
                        f"counts do not add up: read={result.units_read}, loaded={result.units_loaded}, "
                        f"rejected={result.units_rejected}, duplicates={result.units_duplicate}, "
                        f"in database={in_database}"
                    )
    except (XmlFormatError, FileRejected) as exc:
        issues.add("error", exc.code, str(exc))
        result.status = "rejected"
    except psycopg.OperationalError:
        raise  # the database itself is unavailable: stop the whole run
    except Exception as exc:  # noqa: BLE001 - one bad file must not stop the others
        log.exception("Unexpected error on %s", path.name)
        issues.add("error", "UNEXPECTED", f"{type(exc).__name__}: {exc}")
        result.status = "rejected"
    result.issues = issues.issues()
    return result


def _record_issues(conn: psycopg.Connection, run_id: int, file: str, issues: list[Issue]) -> None:
    """Store the problems, outside the file transaction so they survive a rollback."""
    for issue in issues:
        conn.execute(
            "INSERT INTO import_issue (run_id, source_file, severity, code, message) VALUES (%s, %s, %s, %s, %s)",
            (run_id, file, issue.severity, issue.code, issue.message),
        )


def import_files(
    paths: Iterable[Path],
    batch_size: int,
    *,
    skip_existing: bool = False,
    on_result: Callable[[FileResult], None] | None = None,
) -> list[FileResult]:
    """Load several files, one transaction each. A bad file does not stop the others."""
    results: list[FileResult] = []
    with get_connection() as conn:
        conn.autocommit = True
        run_id = conn.execute("INSERT INTO import_run DEFAULT VALUES RETURNING id").fetchone()[0]
        try:
            for path in paths:
                result = import_file(conn, path, batch_size, skip_existing=skip_existing)
                _record_issues(conn, run_id, result.file, result.issues)
                results.append(result)
                if on_result:
                    on_result(result)
        except BaseException:
            try:
                conn.execute("UPDATE import_run SET status = 'failed', finished_at = now() WHERE id = %s", (run_id,))
            except psycopg.Error:
                pass
            raise
        conn.execute("UPDATE import_run SET status = 'success', finished_at = now() WHERE id = %s", (run_id,))
    return results