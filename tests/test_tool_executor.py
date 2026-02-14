"""Tests for ToolExecutor."""

from __future__ import annotations

from pathlib import Path

import pytest

from codesage.config import CodeSageConfig
from codesage.indexer.index import SymbolIndex
from codesage.tools.executor import ToolExecutor


@pytest.fixture
def project_root(tmp_path: Path) -> Path:
    """Create a sample project structure."""
    (tmp_path / "main.py").write_text(
        "from utils import helper\n\n"
        "def main():\n"
        "    print(helper())\n"
    )
    (tmp_path / "utils.py").write_text(
        "def helper():\n"
        "    return 42\n"
    )
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text(
        "class App:\n    pass\n"
    )
    (tmp_path / ".env").write_text("SECRET=password123")
    return tmp_path


@pytest.fixture
async def index(project_root: Path) -> SymbolIndex:
    config = CodeSageConfig()
    idx = SymbolIndex()
    await idx.build(project_root, config)
    return idx


@pytest.fixture
def executor(project_root: Path, index: SymbolIndex) -> ToolExecutor:
    config = CodeSageConfig()
    return ToolExecutor(project_root, index, config)


class TestReadFile:
    @pytest.mark.asyncio
    async def test_read_whole_file(self, executor: ToolExecutor):
        result = await executor.execute("read_file", {"path": "main.py"})
        assert "from utils import helper" in result
        assert "def main()" in result

    @pytest.mark.asyncio
    async def test_read_with_line_range(self, executor: ToolExecutor):
        result = await executor.execute("read_file", {
            "path": "main.py",
            "start_line": 3,
            "end_line": 4,
        })
        assert "def main()" in result
        assert "from utils" not in result

    @pytest.mark.asyncio
    async def test_read_nonexistent_file(self, executor: ToolExecutor):
        result = await executor.execute("read_file", {"path": "nope.py"})
        assert "not found" in result.lower()

    @pytest.mark.asyncio
    async def test_read_excluded_file(self, executor: ToolExecutor):
        result = await executor.execute("read_file", {"path": ".env"})
        assert "denied" in result.lower() or "exclude" in result.lower()


class TestPathTraversal:
    @pytest.mark.asyncio
    async def test_blocked_parent_traversal(self, executor: ToolExecutor):
        result = await executor.execute("read_file", {"path": "../../../etc/passwd"})
        assert "error" in result.lower() or "traversal" in result.lower()

    @pytest.mark.asyncio
    async def test_blocked_absolute_path(self, executor: ToolExecutor):
        result = await executor.execute("read_file", {"path": "/etc/passwd"})
        assert "error" in result.lower() or "traversal" in result.lower()


class TestSearchSymbols:
    @pytest.mark.asyncio
    async def test_search_by_name(self, executor: ToolExecutor):
        result = await executor.execute("search_symbols", {"query": "helper"})
        assert "helper" in result

    @pytest.mark.asyncio
    async def test_search_by_kind(self, executor: ToolExecutor):
        result = await executor.execute("search_symbols", {
            "query": "App",
            "kind": "class",
        })
        assert "App" in result

    @pytest.mark.asyncio
    async def test_search_no_results(self, executor: ToolExecutor):
        result = await executor.execute("search_symbols", {"query": "zzzznonexistent"})
        assert "no symbols" in result.lower()


class TestListFiles:
    @pytest.mark.asyncio
    async def test_list_all(self, executor: ToolExecutor):
        result = await executor.execute("list_files", {"pattern": "**/*.py"})
        assert "main.py" in result
        assert "utils.py" in result

    @pytest.mark.asyncio
    async def test_list_no_matches(self, executor: ToolExecutor):
        result = await executor.execute("list_files", {"pattern": "**/*.xyz"})
        assert "no files" in result.lower()


class TestOutputTruncation:
    @pytest.mark.asyncio
    async def test_truncates_large_output(self, project_root: Path, index: SymbolIndex):
        # Create a large file
        large_content = "x = 1\n" * 5000
        (project_root / "large.py").write_text(large_content)

        config = CodeSageConfig()
        executor = ToolExecutor(project_root, index, config)
        result = await executor.execute("read_file", {"path": "large.py"})

        assert len(result) <= 31_000  # max_output_chars (30000) + truncation message


class TestReadFiles:
    @pytest.mark.asyncio
    async def test_read_multiple_files(self, executor: ToolExecutor):
        result = await executor.execute("read_files", {"paths": ["main.py", "utils.py"]})
        assert "=== main.py ===" in result
        assert "=== utils.py ===" in result
        assert "from utils import helper" in result
        assert "def helper()" in result

    @pytest.mark.asyncio
    async def test_nonexistent_file_in_batch(self, executor: ToolExecutor):
        result = await executor.execute("read_files", {"paths": ["main.py", "nope.py"]})
        assert "=== main.py ===" in result
        assert "=== nope.py ===" in result
        assert "File not found" in result
        # The valid file should still be present
        assert "from utils import helper" in result

    @pytest.mark.asyncio
    async def test_excluded_file_in_batch(self, executor: ToolExecutor):
        result = await executor.execute("read_files", {"paths": ["main.py", ".env"]})
        assert "=== .env ===" in result
        assert "Access denied" in result
        assert "from utils import helper" in result

    @pytest.mark.asyncio
    async def test_empty_paths(self, executor: ToolExecutor):
        result = await executor.execute("read_files", {"paths": []})
        assert "error" in result.lower()

    @pytest.mark.asyncio
    async def test_too_many_files(self, executor: ToolExecutor):
        paths = [f"file{i}.py" for i in range(25)]
        result = await executor.execute("read_files", {"paths": paths})
        assert "too many" in result.lower()


class TestWebSearch:
    @pytest.mark.asyncio
    async def test_web_search_success(self, executor: ToolExecutor):
        mock_results = [
            {"title": "Python docs", "href": "https://python.org", "body": "Official Python docs"},
            {"title": "Tutorial", "href": "https://example.com", "body": "A tutorial"},
        ]

        from unittest.mock import MagicMock, patch

        mock_ddgs_instance = MagicMock()
        mock_ddgs_instance.text = MagicMock(return_value=mock_results)

        with patch("codesage.tools.executor.DDGS", return_value=mock_ddgs_instance):
            result = await executor.execute("web_search", {"query": "python tutorial"})

        assert "Python docs" in result
        assert "https://python.org" in result
        assert "Tutorial" in result

    @pytest.mark.asyncio
    async def test_web_search_not_installed(self, executor: ToolExecutor):
        from unittest.mock import patch

        with patch("codesage.tools.executor.DDGS", None):
            result = await executor.execute("web_search", {"query": "test"})
        assert "duckduckgo-search" in result.lower()


class TestFetchUrl:
    @pytest.mark.asyncio
    async def test_fetch_plain_text(self, executor: ToolExecutor):
        from unittest.mock import AsyncMock, patch

        mock_response = AsyncMock()
        mock_response.content = b"Hello world"
        mock_response.text = "Hello world"
        mock_response.headers = {"content-type": "text/plain"}

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("codesage.tools.executor.httpx.AsyncClient", return_value=mock_client):
            result = await executor.execute("fetch_url", {"url": "https://example.com/test.txt"})
        assert result == "Hello world"

    @pytest.mark.asyncio
    async def test_fetch_json(self, executor: ToolExecutor):
        from unittest.mock import AsyncMock, patch

        mock_response = AsyncMock()
        mock_response.content = b'{"key": "value"}'
        mock_response.text = '{"key": "value"}'
        mock_response.headers = {"content-type": "application/json"}

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("codesage.tools.executor.httpx.AsyncClient", return_value=mock_client):
            result = await executor.execute("fetch_url", {"url": "https://example.com/api"})
        assert '"key": "value"' in result

    @pytest.mark.asyncio
    async def test_fetch_html(self, executor: ToolExecutor):
        from unittest.mock import AsyncMock, patch

        html = "<html><body><p>Hello</p><script>evil()</script></body></html>"
        mock_response = AsyncMock()
        mock_response.content = html.encode()
        mock_response.text = html
        mock_response.headers = {"content-type": "text/html"}

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("codesage.tools.executor.httpx.AsyncClient", return_value=mock_client):
            result = await executor.execute("fetch_url", {"url": "https://example.com"})
        assert "Hello" in result
        assert "evil()" not in result

    @pytest.mark.asyncio
    async def test_blocked_private_ip(self, executor: ToolExecutor):
        result = await executor.execute("fetch_url", {"url": "http://127.0.0.1/admin"})
        assert "not allowed" in result.lower()

        result = await executor.execute("fetch_url", {"url": "http://localhost/admin"})
        assert "not allowed" in result.lower()

        result = await executor.execute("fetch_url", {"url": "http://192.168.1.1/admin"})
        assert "not allowed" in result.lower()

    @pytest.mark.asyncio
    async def test_blocked_scheme(self, executor: ToolExecutor):
        result = await executor.execute("fetch_url", {"url": "ftp://example.com/file"})
        assert "only http" in result.lower()

    @pytest.mark.asyncio
    async def test_fetch_timeout(self, executor: ToolExecutor):
        from unittest.mock import AsyncMock, patch

        import httpx as httpx_mod

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=httpx_mod.TimeoutException("timed out"))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("codesage.tools.executor.httpx.AsyncClient", return_value=mock_client):
            result = await executor.execute("fetch_url", {"url": "https://example.com"})
        assert "timed out" in result.lower()


class TestRunCommand:
    @pytest.mark.asyncio
    async def test_disabled_by_default(self, executor: ToolExecutor):
        result = await executor.execute("run_command", {"command": "echo hello"})
        assert "disabled" in result.lower()

    @pytest.mark.asyncio
    async def test_simple_command(self, project_root: Path, index: SymbolIndex):
        config = CodeSageConfig(agentic={"allow_shell_commands": True})
        executor = ToolExecutor(project_root, index, config)
        result = await executor.execute("run_command", {"command": "echo hello"})
        assert "Exit code: 0" in result
        assert "hello" in result

    @pytest.mark.asyncio
    async def test_blocked_rm_rf(self, project_root: Path, index: SymbolIndex):
        config = CodeSageConfig(agentic={"allow_shell_commands": True})
        executor = ToolExecutor(project_root, index, config)
        result = await executor.execute("run_command", {"command": "rm -rf /"})
        assert "blocked" in result.lower()

    @pytest.mark.asyncio
    async def test_blocked_sudo(self, project_root: Path, index: SymbolIndex):
        config = CodeSageConfig(agentic={"allow_shell_commands": True})
        executor = ToolExecutor(project_root, index, config)
        result = await executor.execute("run_command", {"command": "sudo apt install foo"})
        assert "blocked" in result.lower()

    @pytest.mark.asyncio
    async def test_cwd_is_project_root(self, project_root: Path, index: SymbolIndex):
        config = CodeSageConfig(agentic={"allow_shell_commands": True})
        executor = ToolExecutor(project_root, index, config)
        result = await executor.execute("run_command", {"command": "pwd"})
        assert str(project_root) in result

    @pytest.mark.asyncio
    async def test_stderr_captured(self, project_root: Path, index: SymbolIndex):
        config = CodeSageConfig(agentic={"allow_shell_commands": True})
        executor = ToolExecutor(project_root, index, config)
        result = await executor.execute("run_command", {"command": "echo err >&2"})
        assert "stderr:" in result
        assert "err" in result

    @pytest.mark.asyncio
    async def test_timeout(self, project_root: Path, index: SymbolIndex):
        config = CodeSageConfig(agentic={"allow_shell_commands": True})
        executor = ToolExecutor(project_root, index, config)
        result = await executor.execute("run_command", {"command": "sleep 10", "timeout": 1})
        assert "timed out" in result.lower()


class TestUnknownTool:
    @pytest.mark.asyncio
    async def test_unknown_tool(self, executor: ToolExecutor):
        result = await executor.execute("nonexistent_tool", {})
        assert "unknown" in result.lower()
