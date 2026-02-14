"""Tests for ProjectScanner."""

from __future__ import annotations

from pathlib import Path

import pytest

from codesage.indexer.project import (
    FileNode,
    ProjectInfo,
    ProjectScanner,
    detect_language,
    get_git_diff,
)


class TestDetectLanguage:
    def test_python(self):
        assert detect_language(Path("foo.py")) == "python"

    def test_javascript(self):
        assert detect_language(Path("app.js")) == "javascript"

    def test_typescript(self):
        assert detect_language(Path("app.ts")) == "typescript"
        assert detect_language(Path("app.tsx")) == "typescript"

    def test_go(self):
        assert detect_language(Path("main.go")) == "go"

    def test_rust(self):
        assert detect_language(Path("lib.rs")) == "rust"

    def test_unknown(self):
        assert detect_language(Path("README")) == ""
        assert detect_language(Path("data.xyz")) == ""

    def test_case_insensitive(self):
        assert detect_language(Path("Foo.PY")) == "python"


class TestFileNode:
    def test_render_single_file(self):
        node = FileNode(name="test.py", language="python")
        rendered = node.render()
        assert "test.py" in rendered

    def test_render_directory(self):
        child = FileNode(name="main.py", language="python")
        root = FileNode(name="src", is_dir=True, children=[child])
        rendered = root.render()
        assert "src" in rendered
        assert "main.py" in rendered


class TestProjectScanner:
    def test_scan_empty_directory(self, tmp_path: Path):
        scanner = ProjectScanner()
        info = scanner.scan(tmp_path)
        assert info.root == tmp_path.resolve()
        assert info.files == []
        assert info.language_counts == {}

    def test_scan_with_files(self, tmp_path: Path):
        (tmp_path / "main.py").write_text("print('hello')")
        (tmp_path / "util.py").write_text("def helper(): pass")
        (tmp_path / "README.md").write_text("# Readme")

        scanner = ProjectScanner()
        info = scanner.scan(tmp_path)

        assert len(info.files) == 3
        assert info.language_counts.get("python") == 2
        assert info.language_counts.get("markdown") == 1

    def test_scan_excludes_patterns(self, tmp_path: Path):
        (tmp_path / "main.py").write_text("code")
        (tmp_path / ".env").write_text("SECRET=foo")
        (tmp_path / "credentials.json").write_text("{}")

        scanner = ProjectScanner(exclude_patterns=[".env", "credentials*"])
        info = scanner.scan(tmp_path)

        filenames = [f.name for f in info.files]
        assert "main.py" in filenames
        assert ".env" not in filenames
        assert "credentials.json" not in filenames

    def test_scan_skips_large_files(self, tmp_path: Path):
        (tmp_path / "small.py").write_text("x = 1")
        large = tmp_path / "large.py"
        large.write_bytes(b"x" * 1_100_000)

        scanner = ProjectScanner()
        info = scanner.scan(tmp_path)

        filenames = [f.name for f in info.files]
        assert "small.py" in filenames
        assert "large.py" not in filenames

    def test_scan_builds_file_tree(self, tmp_path: Path):
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "main.py").write_text("code")
        (tmp_path / "README.md").write_text("# Hi")

        scanner = ProjectScanner()
        info = scanner.scan(tmp_path)

        assert info.file_tree is not None
        assert info.file_tree.is_dir
        assert len(info.file_tree.children) >= 1

    def test_scan_nested_directories(self, tmp_path: Path):
        (tmp_path / "a" / "b").mkdir(parents=True)
        (tmp_path / "a" / "b" / "deep.py").write_text("pass")

        scanner = ProjectScanner()
        info = scanner.scan(tmp_path)

        assert any(f.name == "deep.py" for f in info.files)

    def test_scan_respects_gitignore_dirs(self, tmp_path: Path):
        """The manual walker skips __pycache__, node_modules, etc."""
        (tmp_path / "__pycache__").mkdir()
        (tmp_path / "__pycache__" / "cached.pyc").write_text("bytes")
        (tmp_path / "main.py").write_text("code")

        scanner = ProjectScanner()
        info = scanner.scan(tmp_path)

        filenames = [f.name for f in info.files]
        assert "main.py" in filenames
        assert "cached.pyc" not in filenames


class TestProjectInfo:
    def test_summary(self, tmp_path: Path):
        (tmp_path / "a.py").write_text("x")
        (tmp_path / "b.js").write_text("y")

        scanner = ProjectScanner()
        info = scanner.scan(tmp_path)
        summary = info.summary()

        assert "Files: 2" in summary
        assert "python" in summary
        assert "javascript" in summary


class TestGetGitDiff:
    def test_non_git_dir_returns_empty(self, tmp_path: Path):
        result = get_git_diff(tmp_path)
        assert result == ""

    def test_truncation(self, tmp_path: Path):
        result = get_git_diff(tmp_path, max_chars=10)
        # Non-git dir returns "" before truncation matters
        assert result == ""

    def test_git_diff_with_changes(self, tmp_path: Path):
        """Test get_git_diff on a real git repo with changes."""
        import subprocess

        # Initialize a git repo
        subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True)
        subprocess.run(
            ["git", "config", "user.email", "test@test.com"],
            cwd=tmp_path, capture_output=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test"],
            cwd=tmp_path, capture_output=True,
        )

        # Create and commit a file
        (tmp_path / "test.py").write_text("x = 1\n")
        subprocess.run(["git", "add", "."], cwd=tmp_path, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "initial"],
            cwd=tmp_path, capture_output=True,
        )

        # Make a change
        (tmp_path / "test.py").write_text("x = 2\n")

        result = get_git_diff(tmp_path)
        assert "test.py" in result

    def test_git_diff_truncation_large_diff(self, tmp_path: Path):
        """Test that large diffs are truncated."""
        import subprocess

        subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True)
        subprocess.run(
            ["git", "config", "user.email", "test@test.com"],
            cwd=tmp_path, capture_output=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test"],
            cwd=tmp_path, capture_output=True,
        )

        (tmp_path / "big.py").write_text("x = 1\n")
        subprocess.run(["git", "add", "."], cwd=tmp_path, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "initial"],
            cwd=tmp_path, capture_output=True,
        )

        # Write a large change
        (tmp_path / "big.py").write_text("y = 2\n" * 1000)

        result = get_git_diff(tmp_path, max_chars=100)
        assert len(result) <= 120  # 100 + "... (truncated)" suffix


class TestAsyncScan:
    @pytest.mark.asyncio
    async def test_async_scan(self, tmp_path: Path):
        (tmp_path / "test.py").write_text("pass")

        scanner = ProjectScanner()
        info = await scanner.async_scan(tmp_path)

        assert len(info.files) == 1
        assert info.language_counts.get("python") == 1
