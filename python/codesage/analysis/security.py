"""Security analysis stub for Phase 2."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class SecurityFinding:
    """A security issue found in code."""

    severity: str = ""  # critical, high, medium, low, info
    title: str = ""
    description: str = ""
    line: int = 0
    cwe: str = ""


class SecurityAnalyzer:
    """Analyzes code for security vulnerabilities.

    Stub: returns empty results in Phase 0.
    """

    def analyze(self, code: str, language: str = "") -> list[SecurityFinding]:
        return []
