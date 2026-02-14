"""Tests for SymbolIndex."""

from __future__ import annotations

from pathlib import Path

import pytest

from codesage.config import CodeSageConfig
from codesage.indexer.index import SymbolIndex


@pytest.fixture
def sample_project(tmp_path: Path) -> Path:
    """Create a small project with Python files."""
    (tmp_path / "main.py").write_text(
        "from utils import helper\n\n"
        "def main():\n"
        "    helper()\n"
    )
    (tmp_path / "utils.py").write_text(
        "def helper():\n"
        "    return 42\n\n"
        "def unused():\n"
        "    pass\n"
    )
    (tmp_path / "models.py").write_text(
        "class User:\n"
        "    def __init__(self, name):\n"
        "        self.name = name\n"
    )
    return tmp_path


@pytest.fixture
def config() -> CodeSageConfig:
    return CodeSageConfig()


class TestSymbolIndex:
    @pytest.mark.asyncio
    async def test_build(self, sample_project: Path, config: CodeSageConfig):
        index = SymbolIndex()
        assert not index.is_built

        await index.build(sample_project, config)

        assert index.is_built
        assert index.project_info is not None

    @pytest.mark.asyncio
    async def test_lookup(self, sample_project: Path, config: CodeSageConfig):
        index = SymbolIndex()
        await index.build(sample_project, config)

        results = index.lookup("helper")
        assert len(results) >= 1
        assert any(s.name == "helper" for s in results)

    @pytest.mark.asyncio
    async def test_lookup_not_found(self, sample_project: Path, config: CodeSageConfig):
        index = SymbolIndex()
        await index.build(sample_project, config)

        results = index.lookup("nonexistent_symbol")
        assert results == []

    @pytest.mark.asyncio
    async def test_search(self, sample_project: Path, config: CodeSageConfig):
        index = SymbolIndex()
        await index.build(sample_project, config)

        results = index.search("help")
        assert any(s.name == "helper" for s in results)

    @pytest.mark.asyncio
    async def test_get_file_symbols(self, sample_project: Path, config: CodeSageConfig):
        index = SymbolIndex()
        await index.build(sample_project, config)

        symbols = index.get_file_symbols(sample_project / "utils.py")
        func_names = [s.name for s in symbols if s.kind == "function"]
        assert "helper" in func_names
        assert "unused" in func_names

    @pytest.mark.asyncio
    async def test_get_imports(self, sample_project: Path, config: CodeSageConfig):
        index = SymbolIndex()
        await index.build(sample_project, config)

        imports = index.get_imports(sample_project / "main.py")
        assert len(imports) >= 1
        assert any("helper" in s.signature for s in imports)

    @pytest.mark.asyncio
    async def test_rebuild_file(self, sample_project: Path, config: CodeSageConfig):
        index = SymbolIndex()
        await index.build(sample_project, config)

        # Modify a file
        (sample_project / "utils.py").write_text(
            "def helper():\n"
            "    return 99\n\n"
            "def new_func():\n"
            "    pass\n"
        )

        index.rebuild_file(sample_project / "utils.py")

        # Old symbol should be updated
        results = index.lookup("new_func")
        assert len(results) >= 1

        # Removed symbol should be gone
        results = index.lookup("unused")
        assert len(results) == 0

    @pytest.mark.asyncio
    async def test_get_symbols_by_kind(self, sample_project: Path, config: CodeSageConfig):
        index = SymbolIndex()
        await index.build(sample_project, config)

        classes = index.get_symbols_by_kind("class")
        assert any(s.name == "User" for s in classes)

        functions = index.get_symbols_by_kind("function")
        assert any(s.name == "helper" for s in functions)
