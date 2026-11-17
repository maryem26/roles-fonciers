""" Ce fichier regarde les fichiers xml et résume la taille, la version, les erreurs , analyse explo"""
"""Inventory of all XML files: size, encoding, VERSION, RLM01A, RLM02A."""
import csv
import re
import statistics
import sys
from collections import Counter
from pathlib import Path

from lxml import etree

WANTED = {"VERSION", "RLM01A", "RLM02A"}


def declared_encoding(path: Path) -> str:
    with open(path, "rb") as f:
        head = f.read(200)
    m = re.search(rb'encoding=["\']([^"\']+)', head)
    return m.group(1).decode() if m else "absent"


def general_fields(path: Path) -> dict:
    found = {}
    try:
        for _, el in etree.iterparse(str(path), events=("end",), huge_tree=True):
            name = etree.QName(el).localname
            if name in WANTED and name not in found:
                found[name] = (el.text or "").strip()
            if len(found) == len(WANTED):
                break
    except etree.XMLSyntaxError as e:
        found["error"] = str(e)[:100]
    return found


def main(folder: str) -> None:
    files = sorted(Path(folder).rglob("*.[xX][mM][lL]"))
    rows = []
    for p in files:
        info = general_fields(p)
        rows.append({
            "file": p.name,
            "size_mb": round(p.stat().st_size / 1_048_576, 3),
            "encoding": declared_encoding(p),
            "version": info.get("VERSION", ""),
            "municipality": info.get("RLM01A", ""),
            "year": info.get("RLM02A", ""),
            "error": info.get("error", ""),
        })

    out = Path("data/inventory.csv")
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=rows[0].keys())
        w.writeheader()
        w.writerows(rows)

    sizes = sorted(r["size_mb"] for r in rows)
    print(f"Files: {len(rows)} | total: {sum(sizes):.0f} MB")
    print(f"Size MB  min={sizes[0]}  median={statistics.median(sizes)}  max={sizes[-1]}")
    print("Prefixes :", Counter(r["file"][:2] for r in rows).most_common())
    print("Encodings:", Counter(r["encoding"] for r in rows).most_common())
    print("Versions :", Counter(r["version"] for r in rows).most_common())
    print("Years    :", Counter(r["year"] for r in rows).most_common())
    print("Errors   :", sum(1 for r in rows if r["error"]))
    by_size = sorted(rows, key=lambda r: r["size_mb"])
    print("Smallest :", by_size[0]["file"])
    print("Median   :", by_size[len(by_size) // 2]["file"])
    print("Largest  :", by_size[-1]["file"])


if __name__ == "__main__":
    main(sys.argv[1])