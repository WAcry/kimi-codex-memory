"""Bounded, content-free diagnostics for recoverable item failures."""

from collections import Counter

from .errors import MemoryErrorBase
from .files import digest


class Issues:
    def __init__(self):
        self.counts: Counter[str] = Counter()
        self.samples: list[dict] = []

    def add(self, stage: str, error: Exception, source: str | None = None) -> None:
        code = error.code if isinstance(error, MemoryErrorBase) else type(error).__name__
        self.counts[stage + ":" + code] += 1
        if len(self.samples) < 10:
            sample = {"stage": stage, "code": code}
            if source is not None:
                sample["item"] = digest(source)[:16]
            self.samples.append(sample)

    @property
    def count(self) -> int:
        return sum(self.counts.values())

    def summary(self) -> dict:
        return {"count": self.count, "counts": dict(self.counts), "samples": self.samples}
