"""Project scanner — walks project directory, builds file tree and metadata."""

from __future__ import annotations

import asyncio
import fnmatch
import logging
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

# Extension → language mapping
EXTENSION_LANGUAGES: dict[str, str] = {
    ".py": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".go": "go",
    ".rs": "rust",
    ".java": "java",
    ".c": "c",
    ".h": "c",
    ".cpp": "cpp",
    ".cc": "cpp",
    ".cxx": "cpp",
    ".hpp": "cpp",
    ".hxx": "cpp",
    ".lua": "lua",
    ".rb": "ruby",
    ".php": "php",
    ".sh": "bash",
    ".bash": "bash",
    ".zsh": "zsh",
    ".toml": "toml",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".json": "json",
    ".md": "markdown",
    ".css": "css",
    ".scss": "scss",
    ".html": "html",
    ".xml": "xml",
    ".sql": "sql",
    ".kt": "kotlin",
    ".swift": "swift",
    ".cs": "csharp",
}

MAX_FILE_SIZE = 1_000_000  # 1MB


@dataclass
class FileNode:
    """A node in the project file tree."""

    name: str
    is_dir: bool = False
    children: list[FileNode] = field(default_factory=list)
    language: str = ""

    def render(self, prefix: str = "", is_last: bool = True) -> str:
        """Render this node as a tree string."""
        connector = "└── " if is_last else "├── "
        line = prefix + connector + self.name
        lines = [line]
        if self.is_dir and self.children:
            extension = "    " if is_last else "│   "
            for i, child in enumerate(self.children):
                lines.append(child.render(prefix + extension, i == len(self.children) - 1))
        return "\n".join(lines)


@dataclass
class ProjectInfo:
    """Information about a scanned project."""

    root: Path = field(default_factory=lambda: Path("."))
    file_tree: FileNode | None = None
    files: list[Path] = field(default_factory=list)
    language_counts: dict[str, int] = field(default_factory=dict)

    def summary(self) -> str:
        """Compact text representation of the project."""
        parts = [f"Project: {self.root.name}"]
        parts.append(f"Files: {len(self.files)}")

        if self.language_counts:
            lang_str = ", ".join(
                f"{lang}: {count}" for lang, count in sorted(
                    self.language_counts.items(), key=lambda x: -x[1]
                )
            )
            parts.append(f"Languages: {lang_str}")

        if self.file_tree:
            parts.append("")
            parts.append("File structure:")
            parts.append(self.file_tree.render())

        return "\n".join(parts)


def detect_language(path: Path) -> str:
    """Detect language from file extension."""
    return EXTENSION_LANGUAGES.get(path.suffix.lower(), "")


class ProjectScanner:
    """Scans a project directory for structure information."""

    def __init__(self, exclude_patterns: list[str] | None = None) -> None:
        self._exclude_patterns = exclude_patterns or []

    def _is_excluded(self, path: Path, root: Path) -> bool:
        """Check if a path matches any exclude pattern."""
        rel = str(path.relative_to(root))
        name = path.name
        for pattern in self._exclude_patterns:
            if fnmatch.fnmatch(name, pattern) or fnmatch.fnmatch(rel, pattern):
                return True
        return False

    def _get_git_files(self, root: Path) -> list[Path] | None:
        """Get tracked files via git ls-files."""
        try:
            result = subprocess.run(
                ["git", "ls-files", "-z"],
                cwd=root,
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode != 0:
                return None
            files = [
                root / f for f in result.stdout.split("\0")
                if f  # skip empty strings from trailing \0
            ]
            return files
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return None

    def _walk_directory(self, root: Path) -> list[Path]:
        """Walk directory manually, respecting .gitignore-style patterns."""
        skip_dirs = {
            ".git", "__pycache__", "node_modules", ".venv", "venv",
            ".mypy_cache", ".pytest_cache", ".ruff_cache", "dist", "build",
            ".tox", ".eggs", "*.egg-info",
        }
        files: list[Path] = []
        for entry in sorted(root.rglob("*")):
            if not entry.is_file():
                continue
            # Skip common unneeded directories
            parts = entry.relative_to(root).parts
            if any(
                any(fnmatch.fnmatch(part, pat) for pat in skip_dirs)
                for part in parts[:-1]
            ):
                continue
            files.append(entry)
        return files

    def _build_file_tree(self, root: Path, files: list[Path]) -> FileNode:
        """Build a FileNode tree from a list of files."""
        tree = FileNode(name=root.name, is_dir=True)
        nodes: dict[Path, FileNode] = {root: tree}

        for file_path in sorted(files):
            rel = file_path.relative_to(root)
            # Ensure parent directories exist
            current = root
            for part in rel.parts[:-1]:
                child_path = current / part
                if child_path not in nodes:
                    dir_node = FileNode(name=part, is_dir=True)
                    nodes[current].children.append(dir_node)
                    nodes[child_path] = dir_node
                current = child_path

            # Add file node
            file_node = FileNode(
                name=rel.parts[-1],
                language=detect_language(file_path),
            )
            nodes[current].children.append(file_node)

        return tree

    def scan(self, root: Path | None = None) -> ProjectInfo:
        """Scan the project directory.

        Uses git ls-files if available, falls back to manual directory walk.
        Skips files >1MB and excluded patterns.
        """
        root = (root or Path(".")).resolve()

        # Get file list
        files = self._get_git_files(root)
        if files is None:
            files = self._walk_directory(root)

        # Filter: exclude patterns, size limit
        filtered: list[Path] = []
        for f in files:
            if not f.is_file():
                continue
            if self._is_excluded(f, root):
                continue
            try:
                if f.stat().st_size > MAX_FILE_SIZE:
                    continue
            except OSError:
                continue
            filtered.append(f)

        # Count languages
        language_counts: dict[str, int] = {}
        for f in filtered:
            lang = detect_language(f)
            if lang:
                language_counts[lang] = language_counts.get(lang, 0) + 1

        # Build tree
        file_tree = self._build_file_tree(root, filtered)

        return ProjectInfo(
            root=root,
            file_tree=file_tree,
            files=filtered,
            language_counts=language_counts,
        )

    async def async_scan(self, root: Path | None = None) -> ProjectInfo:
        """Async wrapper — runs scan in thread pool."""
        return await asyncio.to_thread(self.scan, root)
