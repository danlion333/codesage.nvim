"""In-memory searchable symbol index."""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from pathlib import Path

from codesage.config import CodeSageConfig
from codesage.indexer.project import ProjectInfo, ProjectScanner, detect_language
from codesage.indexer.symbols import Symbol, SymbolExtractor

logger = logging.getLogger(__name__)


class SymbolIndex:
    """In-memory index of all symbols in a project."""

    def __init__(self) -> None:
        self._symbols_by_file: dict[str, list[Symbol]] = defaultdict(list)
        self._symbols_by_name: dict[str, list[Symbol]] = defaultdict(list)
        self._symbols_by_kind: dict[str, list[Symbol]] = defaultdict(list)
        self._extractor = SymbolExtractor()
        self._project_info: ProjectInfo | None = None
        self._built = False

    @property
    def is_built(self) -> bool:
        return self._built

    @property
    def project_info(self) -> ProjectInfo | None:
        return self._project_info

    async def build(self, root: Path, config: CodeSageConfig) -> None:
        """Scan project and extract symbols from all files.

        Runs in background via asyncio.to_thread for the CPU-bound parts.
        """
        scanner = ProjectScanner(exclude_patterns=config.privacy.exclude_patterns)
        self._project_info = await scanner.async_scan(root)

        # Extract symbols from all files (in thread pool)
        await asyncio.to_thread(self._extract_all_symbols)
        self._built = True
        logger.info(
            "Index built: %d files, %d symbols",
            len(self._project_info.files),
            sum(len(syms) for syms in self._symbols_by_file.values()),
        )

    def _extract_all_symbols(self) -> None:
        """Extract symbols from all project files (sync, for thread pool)."""
        if not self._project_info:
            return
        for file_path in self._project_info.files:
            language = detect_language(file_path)
            if not language:
                continue
            symbols = self._extractor.extract_file(file_path, language)
            self._index_symbols(str(file_path), symbols)

    def _index_symbols(self, file_key: str, symbols: list[Symbol]) -> None:
        """Add symbols to all lookup indices."""
        self._symbols_by_file[file_key] = symbols
        for sym in symbols:
            self._symbols_by_name[sym.name].append(sym)
            self._symbols_by_kind[sym.kind].append(sym)

    def rebuild_file(self, path: Path, language: str = "") -> None:
        """Incrementally re-index a single file.

        Call this on file save to keep the index fresh.
        """
        file_key = str(path.resolve())

        # Remove old symbols for this file from name/kind indices
        old_symbols = self._symbols_by_file.get(file_key, [])
        for sym in old_symbols:
            name_list = self._symbols_by_name.get(sym.name, [])
            self._symbols_by_name[sym.name] = [s for s in name_list if s.file != file_key]
            kind_list = self._symbols_by_kind.get(sym.kind, [])
            self._symbols_by_kind[sym.kind] = [s for s in kind_list if s.file != file_key]

        # Re-extract
        if not language:
            language = detect_language(path)
        symbols = self._extractor.extract_file(path, language)
        self._index_symbols(file_key, symbols)

    def lookup(self, name: str) -> list[Symbol]:
        """Look up symbols by exact name."""
        return self._symbols_by_name.get(name, [])

    def search(self, query: str) -> list[Symbol]:
        """Search symbols by substring match on name."""
        query_lower = query.lower()
        results: list[Symbol] = []
        for name, symbols in self._symbols_by_name.items():
            if query_lower in name.lower():
                results.extend(symbols)
        return results

    def get_file_symbols(self, path: Path) -> list[Symbol]:
        """Get all symbols in a specific file."""
        return self._symbols_by_file.get(str(path.resolve()), [])

    def get_imports(self, path: Path) -> list[Symbol]:
        """Get all import symbols from a specific file."""
        file_key = str(path.resolve())
        return [
            sym for sym in self._symbols_by_file.get(file_key, [])
            if sym.kind == "import"
        ]

    def get_symbols_by_kind(self, kind: str) -> list[Symbol]:
        """Get all symbols of a specific kind."""
        return self._symbols_by_kind.get(kind, [])
