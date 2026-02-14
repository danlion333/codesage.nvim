"""Code quality analysis stub for Phase 2."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class QualityFinding:
    """A code quality observation."""

    category: str = ""
    title: str = ""
    description: str = ""
    line: int = 0


class QualityAnalyzer:
    """Analyzes code for quality issues.

    Stub: returns empty results in Phase 0.
    """

    def analyze(self, code: str, language: str = "") -> list[QualityFinding]:
        return []
