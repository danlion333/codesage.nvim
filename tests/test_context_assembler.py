"""Tests for ContextAssembler."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from codesage.config import CodeSageConfig, ContextConfig
from codesage.indexer.context import AssembledContext, ContextAssembler
from codesage.indexer.index import SymbolIndex


@pytest.fixture
def sample_project(tmp_path: Path) -> Path:
    """Create a small project."""
    (tmp_path / "main.py").write_text(
        "from utils import helper\n\n"
        "def main():\n"
        "    result = helper()\n"
        "    print(result)\n"
    )
    (tmp_path / "utils.py").write_text(
        "def helper():\n"
        "    return 42\n\n"
        "class Config:\n"
        "    debug = True\n"
    )
    return tmp_path


@pytest.fixture
async def built_index(sample_project: Path) -> SymbolIndex:
    config = CodeSageConfig()
    index = SymbolIndex()
    await index.build(sample_project, config)
    return index


class TestAssembledContext:
    def test_render_empty(self):
        ctx = AssembledContext()
        assert ctx.render() == ""

    def test_render_with_project_summary(self):
        ctx = AssembledContext(project_summary="Project: test\nFiles: 5")
        rendered = ctx.render()
        assert "## Project Context" in rendered
        assert "Project: test" in rendered

    def test_render_with_all_sections(self):
        ctx = AssembledContext(
            project_summary="Project info",
            file_context="File context here",
            import_context="Import info",
            related_symbols="Related info",
        )
        rendered = ctx.render()
        assert "## Project Context" in rendered
        assert "## Current File Context" in rendered
        assert "## Imported Symbols" in rendered
        assert "## Related Definitions" in rendered

    def test_render_order(self):
        ctx = AssembledContext(
            project_summary="1-project",
            git_diff="2-diff",
            file_context="3-file",
            import_context="4-import",
            related_symbols="5-related",
        )
        rendered = ctx.render()
        proj_pos = rendered.index("1-project")
        diff_pos = rendered.index("2-diff")
        file_pos = rendered.index("3-file")
        import_pos = rendered.index("4-import")
        related_pos = rendered.index("5-related")
        assert proj_pos < diff_pos < file_pos < import_pos < related_pos

    def test_render_with_git_diff(self):
        ctx = AssembledContext(git_diff="diff --git a/foo.py")
        rendered = ctx.render()
        assert "## Recent Changes" in rendered
        assert "diff --git a/foo.py" in rendered

    def test_render_without_git_diff(self):
        ctx = AssembledContext(project_summary="Project info")
        rendered = ctx.render()
        assert "## Recent Changes" not in rendered


class TestContextAssembler:
    @pytest.mark.asyncio
    async def test_assemble_basic(self, built_index: SymbolIndex):
        config = ContextConfig(max_context_tokens=8000)
        assembler = ContextAssembler(built_index, config)

        result = assembler.assemble(
            code="result = helper()",
            language="python",
        )

        assert isinstance(result, AssembledContext)
        assert result.selected_code == "result = helper()"
        assert result.total_tokens > 0

    @pytest.mark.asyncio
    async def test_assemble_with_file_context(self, built_index: SymbolIndex, sample_project: Path):
        config = ContextConfig(max_context_tokens=8000)
        assembler = ContextAssembler(built_index, config)

        filepath = str(sample_project / "main.py")
        file_content = (sample_project / "main.py").read_text()

        result = assembler.assemble(
            code="result = helper()",
            filepath=filepath,
            file_content=file_content,
            language="python",
        )

        assert result.file_context != ""

    @pytest.mark.asyncio
    async def test_assemble_includes_project_summary(self, built_index: SymbolIndex):
        config = ContextConfig(max_context_tokens=8000, include_project_summary=True)
        assembler = ContextAssembler(built_index, config)

        result = assembler.assemble(code="x = 1", language="python")

        assert result.project_summary != ""
        assert "Files:" in result.project_summary

    @pytest.mark.asyncio
    async def test_assemble_respects_disabled_summary(self, built_index: SymbolIndex):
        config = ContextConfig(max_context_tokens=8000, include_project_summary=False)
        assembler = ContextAssembler(built_index, config)

        result = assembler.assemble(code="x = 1", language="python")

        assert result.project_summary == ""

    @pytest.mark.asyncio
    async def test_assemble_finds_related_symbols(self, built_index: SymbolIndex):
        config = ContextConfig(
            max_context_tokens=8000,
            include_related_symbols=True,
        )
        assembler = ContextAssembler(built_index, config)

        result = assembler.assemble(
            code="result = helper()",
            language="python",
        )

        # "helper" is defined in utils.py, should be found as related
        assert result.related_symbols != ""
        assert "helper" in result.related_symbols

    @pytest.mark.asyncio
    async def test_assemble_token_budget(self, built_index: SymbolIndex):
        config = ContextConfig(max_context_tokens=100)  # very small budget
        assembler = ContextAssembler(built_index, config)

        result = assembler.assemble(code="x = 1", language="python")

        # Should still work without error even with small budget
        assert isinstance(result, AssembledContext)

    @pytest.mark.asyncio
    async def test_render_output(self, built_index: SymbolIndex):
        config = ContextConfig(max_context_tokens=8000)
        assembler = ContextAssembler(built_index, config)

        result = assembler.assemble(code="helper()", language="python")
        rendered = result.render()

        assert isinstance(rendered, str)

    @pytest.mark.asyncio
    async def test_assemble_with_git_diff(self, built_index: SymbolIndex, sample_project: Path):
        config = ContextConfig(max_context_tokens=8000, include_git_diff=True)
        assembler = ContextAssembler(built_index, config, project_root=sample_project)

        with patch("codesage.indexer.context.get_git_diff", return_value="diff --git a/foo.py"):
            result = assembler.assemble(code="x = 1", language="python")

        assert result.git_diff == "diff --git a/foo.py"
        rendered = result.render()
        assert "## Recent Changes" in rendered

    @pytest.mark.asyncio
    async def test_assemble_git_diff_disabled(self, built_index: SymbolIndex, sample_project: Path):
        config = ContextConfig(max_context_tokens=8000, include_git_diff=False)
        assembler = ContextAssembler(built_index, config, project_root=sample_project)

        with patch("codesage.indexer.context.get_git_diff", return_value="some diff"):
            result = assembler.assemble(code="x = 1", language="python")

        assert result.git_diff == ""

    @pytest.mark.asyncio
    async def test_assemble_git_diff_no_project_root(self, built_index: SymbolIndex):
        config = ContextConfig(max_context_tokens=8000, include_git_diff=True)
        assembler = ContextAssembler(built_index, config)  # no project_root

        result = assembler.assemble(code="x = 1", language="python")

        assert result.git_diff == ""
