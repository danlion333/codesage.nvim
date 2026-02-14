"""Architecture analysis stub for Phase 2."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ArchitectureFinding:
    """An architecture observation or concern."""

    category: str = ""
    title: str = ""
    description: str = ""


class ArchitectureAnalyzer:
    """Analyzes code for architectural patterns and concerns.

    Stub: returns empty results in Phase 0.
    """

    def analyze(self, code: str, language: str = "") -> list[ArchitectureFinding]:
        return []
