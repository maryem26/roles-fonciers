"""Collect import problems, aggregated per type so the log stays readable.

A problem can repeat thousands of times in a big file. The collector keeps one
entry per (severity, code, key), with the number of occurrences and a few
examples, instead of one record per occurrence.
"""

from dataclasses import dataclass, field

MAX_EXAMPLES = 3


@dataclass(frozen=True)
class Issue:
    severity: str  # "warning" or "error"
    code: str  # e.g. "ZERO_OR_MISSING_VALUE"
    message: str


@dataclass
class _Entry:
    severity: str
    code: str
    count: int = 0
    examples: list[str] = field(default_factory=list)


class IssueCollector:
    def __init__(self) -> None:
        self._entries: dict[tuple[str, str, str], _Entry] = {}

    def add(self, severity: str, code: str, example: str, key: str = "") -> None:
        entry = self._entries.setdefault((severity, code, key), _Entry(severity, code))
        entry.count += 1
        if len(entry.examples) < MAX_EXAMPLES:
            entry.examples.append(example)

    def issues(self) -> list[Issue]:
        return [
            Issue(e.severity, e.code, f"{e.count} occurrence(s). Examples: " + " | ".join(e.examples))
            for e in self._entries.values()
        ]