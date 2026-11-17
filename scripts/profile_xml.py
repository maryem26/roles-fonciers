import sys
from collections import Counter, defaultdict
from lxml import etree

counts = Counter()
samples = defaultdict(set)
stack = []
for event, el in etree.iterparse(sys.argv[1], events=("start", "end"), huge_tree=True):
    if event == "start":
        stack.append(etree.QName(el).localname)
        continue
    p = "/".join(stack)
    counts[p] += 1
    text = (el.text or "").strip()
    if text and len(samples[p]) < 200:
        samples[p].add(text[:60])
    stack.pop()
    el.clear()

print("count\tdistinct\tpath\texamples")
for p, n in sorted(counts.items()):
    s = sorted(samples[p])
    print(f"{n}\t{len(s)}\t{p}\t{s[:5]}")