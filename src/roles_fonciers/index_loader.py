"""Load the municipality index CSV into the municipality table.

Reading the CSV (parse_index) is kept separate from writing to the database
(load_municipalities), so the parsing rules can be tested without a database.
"""

import csv
import logging
import re
from pathlib import Path

from roles_fonciers.database import get_connection

log = logging.getLogger(__name__)

EXPECTED_HEADER = ["code géographique", "nom du territoire", "lien"]

Row = tuple[str, str | None]


def normalize_municipality_code(raw: str) -> str | None:
    """Return the code on 5 characters, or None if it is not a valid code.

    Numeric codes are padded with zeros: the index writes 1023, the files use
    01023. Other codes (such as NR020) already have 5 letters or digits.
    """
    code = raw.strip().upper()
    if re.fullmatch(r"[0-9]{1,5}", code):
        return code.zfill(5)
    if re.fullmatch(r"[0-9A-Z]{5}", code):
        return code
    return None


def parse_index(csv_path: Path) -> tuple[list[Row], list[str]]:
    """Read the index CSV.

    Returns (rows, problems). Each row is (code on 5 characters, name or None).
    Each problem is a readable message for a line that was skipped.
    Raises ValueError if the header is not the expected one.
    """
    rows: list[Row] = []
    problems: list[str] = []
    seen: set[str] = set()

    # utf-8-sig removes the BOM that some tools add at the start of a CSV
    with open(csv_path, encoding="utf-8-sig", newline="") as file:
        reader = csv.reader(file)
        header = next(reader, None)
        if header is None or [h.strip().lower() for h in header[:3]] != EXPECTED_HEADER:
            raise ValueError(f"Unexpected header in {csv_path}: {header}")

        for line_number, row in enumerate(reader, start=2):
            if not row:  # blank line
                continue
            if len(row) < 3:
                problems.append(f"line {line_number}: expected 3 columns, got {len(row)}")
                continue

            code = normalize_municipality_code(row[0])
            if code is None:
                problems.append(f"line {line_number}: invalid municipality code {row[0]!r}")
                continue

            if code in seen:
                problems.append(f"line {line_number}: duplicate municipality code {code}")
                continue
            seen.add(code)

            name = row[1].strip() or None  # a missing name must not hide the code
            rows.append((code, name))

    return rows, problems


def load_municipalities(csv_path: Path) -> tuple[int, int]:
    """Insert or update the municipalities. Returns (loaded, skipped)."""
    rows, problems = parse_index(csv_path)
    for problem in problems:
        log.warning("Index skipped: %s", problem)

    with get_connection() as conn:  # commits at the end, rolls back on error
        with conn.cursor() as cur:
            cur.executemany(
                """
                INSERT INTO municipality (municipality_code, name)
                VALUES (%s, %s)
                ON CONFLICT (municipality_code)
                DO UPDATE SET name = EXCLUDED.name;
                """,
                rows,
            )

    return len(rows), len(problems)