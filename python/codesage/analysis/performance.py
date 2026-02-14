"""Performance analysis stub for Phase 2."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class PerformanceFinding:
    """A performance issue found in code."""

    severity: str = ""
    title: str = ""
    description: str = ""
    line: int = 0


class PerformanceAnalyzer:
    """Analyzes code for performance issues.

    Stub: returns empty results in Phase 0.
    """

    def analyze(self, code: str, language: str = "") -> list[PerformanceFinding]:
        return []
