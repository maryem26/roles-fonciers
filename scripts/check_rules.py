import sys
from collections import Counter
from lxml import etree


def val(ue, tag):
    el = ue.find(tag)
    return el.text.strip() if el is not None and el.text else None


units = 0
keys = Counter()
sum_errors = 0
no_values = []

for _, ue in etree.iterparse(sys.argv[1], tag="RLUEx", huge_tree=True):
    units += 1
    mat = ue.find("RL0104")
    key = tuple((c.tag, c.text) for c in mat) if mat is not None else None
    keys[key] += 1

    terrain, building, total = (val(ue, t) for t in ("RL0402A", "RL0403A", "RL0404A"))
    if terrain is None or total is None:
        no_values.append(key)
    elif float(terrain) + float(building or 0) != float(total):
        sum_errors += 1

    ue.clear()
    while ue.getprevious() is not None:
        del ue.getparent()[0]

duplicates = sum(1 for n in keys.values() if n > 1)
print("Unités            :", units)
print("Matricules uniques:", len(keys))
print("Matricules en double:", duplicates)
print("Erreurs terrain + bâtiment != immeuble:", sum_errors)
print("Unités sans valeur terrain/immeuble:", len(no_values), no_values[:3])