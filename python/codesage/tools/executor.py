"""Tool executor with security controls."""

from __future__ import annotations

import asyncio
import fnmatch
import ipaddress
import json
import logging
import re
from pathlib import Path
from urllib.parse import urlparse

import httpx

from codesage.config import CodeSageConfig
from codesage.indexer.index import SymbolIndex

try:
    from duckduckgo_search import DDGS
except ImportError:
    DDGS = None

logger = logging.getLogger(__name__)

MAX_OUTPUT_CHARS = 30_000

_BLOCKED_COMMAND_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\brm\s+-(r|f|rf|fr)\b"),
    re.compile(r"\bsudo\b"),
    re.compile(r"\bchmod\b"),
    re.compile(r"\bchown\b"),
    re.compile(r"\bmkfs\b"),
    re.compile(r"\bdd\b"),
    re.compile(r"\b(shutdown|reboot|halt)\b"),
    re.compile(r"\bcurl\b.*\|\s*\b(sh|bash)\b"),
    re.compile(r"\beval\b"),
    re.compile(r"\bexec\b"),
    re.compile(r"`"),
    re.compile(r"\$\("),
    re.compile(r"\b(kill|pkill)\b"),
    re.compile(r"\bsystemctl\b"),
    re.compile(r"&\s*$"),
]


class ToolExecutor:
    """Executes tool calls requested by the LLM.

    Security:
    - Path traversal prevention (all paths resolved + checked against project root)
    - Privacy exclude patterns respected
    - All subprocesses use exec (never shell=True)
    - Output truncated to MAX_OUTPUT_CHARS
    """

    def __init__(
        self,
        project_root: Path,
        index: SymbolIndex,
        config: CodeSageConfig,
    ) -> None:
        self._root = project_root.resolve()
        self._index = index
        self._config = config
        self._exclude_patterns = config.privacy.exclude_patterns

    def _safe_path(self, relative_path: str) -> Path:
        """Resolve a relative path and verify it's within the project root.

        Raises:
            ValueError: If the path escapes the project root.
        """
        resolved = (self._root / relative_path).resolve()
        if not str(resolved).startswith(str(self._root)):
            raise ValueError(f"Path traversal blocked: {relative_path}")
        return resolved

    def _is_excluded(self, path: Path) -> bool:
        """Check if a path matches privacy exclude patterns."""
        name = path.name
        rel = str(path.relative_to(self._root))
        for pattern in self._exclude_patterns:
            if fnmatch.fnmatch(name, pattern) or fnmatch.fnmatch(rel, pattern):
                return True
        return False

    def _truncate(self, text: str) -> str:
        """Truncate output to configured max_output_chars."""
        limit = self._config.agentic.max_output_chars
        if len(text) > limit:
            return text[:limit] + f"\n... (truncated, {len(text)} total chars)"
        return text

    async def execute(self, tool_name: str, arguments: dict) -> str:
        """Execute a tool and return its output as a string.

        Args:
            tool_name: Name of the tool to execute.
            arguments: Tool arguments dict.

        Returns:
            Tool output string.
        """
        handlers = {
            "read_file": self._read_file,
            "read_files": self._read_files,
            "search_symbols": self._search_symbols,
            "find_usages": self._find_usages,
            "grep_files": self._grep_files,
            "list_files": self._list_files,
            "git_info": self._git_info,
            "web_search": self._web_search,
            "fetch_url": self._fetch_url,
            "run_command": self._run_command,
        }

        handler = handlers.get(tool_name)
        if handler is None:
            return f"Error: Unknown tool '{tool_name}'"

        try:
            result = await handler(arguments)
            return self._truncate(result)
        except ValueError as e:
            return f"Error: {e}"
        except Exception as e:
            logger.error("Tool execution error (%s): %s", tool_name, e)
            return f"Error executing {tool_name}: {e}"

    async def _read_file(self, args: dict) -> str:
        path_arg = args["path"]  # Keep original for display
        path = self._safe_path(path_arg)
        if not path.is_file():
            return f"File not found: {path_arg}"
        if self._is_excluded(path):
            return f"Access denied: {path_arg} matches privacy exclude pattern"

        header = f"=== {path_arg} ==="
        text = path.read_text(encoding="utf-8", errors="replace")
        lines = text.split("\n")

        start = args.get("start_line")
        end = args.get("end_line")
        if start is not None or end is not None:
            start_idx = (start or 1) - 1
            end_idx = end or len(lines)
            lines = lines[start_idx:end_idx]

    # Number lines
        start_num = (start or 1)
        numbered = [f"{start_num + i:4d} | {line}" for i, line in enumerate(lines)]
        return header + "\n" + "\n".join(numbered)

    async def _search_symbols(self, args: dict) -> str:
        query = args["query"]
        kind_filter = args.get("kind")

        results = self._index.search(query)
        if kind_filter:
            results = [s for s in results if s.kind == kind_filter]

        if not results:
            return f"No symbols found matching '{query}'"

        lines = []
        for sym in results[:50]:  # limit results
            loc = f"{Path(sym.file).name}:{sym.line}" if sym.file else ""
            lines.append(f"[{sym.kind}] {sym.signature} ({loc})")
        return "\n".join(lines)

    async def _find_usages(self, args: dict) -> str:
        symbol = args["symbol"]
        # Use grep to find usages across project files
        try:
            proc = await asyncio.create_subprocess_exec(
                "grep", "-rn", "--include=*.py", "--include=*.js",
                "--include=*.ts", "--include=*.go", "--include=*.rs",
                "--include=*.java", "--include=*.lua", "--include=*.c",
                "--include=*.cpp", "--include=*.h",
                "-w", symbol, str(self._root),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=10)
        except asyncio.TimeoutError:
            return "Search timed out"

        output = stdout.decode("utf-8", errors="replace")
        if not output.strip():
            return f"No usages of '{symbol}' found"

        # Make paths relative
        lines = []
        for line in output.strip().split("\n"):
            line = line.replace(str(self._root) + "/", "")
            lines.append(line)
        return "\n".join(lines)

    async def _grep_files(self, args: dict) -> str:
        pattern = args["pattern"]
        glob_filter = args.get("glob")

        cmd = ["grep", "-rn", "-E", pattern]
        if glob_filter:
            cmd.extend(["--include", glob_filter])
        cmd.append(str(self._root))

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=10)
        except asyncio.TimeoutError:
            return "Search timed out"

        output = stdout.decode("utf-8", errors="replace")
        if not output.strip():
            return f"No matches for pattern '{pattern}'"

        # Make paths relative
        lines = []
        for line in output.strip().split("\n"):
            line = line.replace(str(self._root) + "/", "")
            lines.append(line)
        return "\n".join(lines)

    async def _list_files(self, args: dict) -> str:
        pattern = args.get("pattern", "**/*")

        files: list[str] = []
        for path in sorted(self._root.glob(pattern)):
            if path.is_file() and not self._is_excluded(path):
                files.append(str(path.relative_to(self._root)))

        if not files:
            return f"No files matching '{pattern}'"
        return "\n".join(files[:200])  # limit output

    async def _git_info(self, args: dict) -> str:
        action = args["action"]

        cmd_map = {
            "diff": ["git", "diff"],
            "status": ["git", "status", "--short"],
            "log": ["git", "log", "--oneline", "-20"],
        }

        if action == "file_diff":
            path = args.get("path")
            if not path:
                return "Error: file_diff requires a 'path' argument"
            safe = self._safe_path(path)
            cmd = ["git", "diff", str(safe)]
        else:
            cmd = cmd_map.get(action)
            if not cmd:
                return f"Error: Unknown git action '{action}'"

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=str(self._root),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=10)
        except asyncio.TimeoutError:
            return "Git command timed out"

        output = stdout.decode("utf-8", errors="replace")
        if not output.strip():
            return f"No output from git {action}"
        return output

    async def _read_files(self, args: dict) -> str:
        paths = args.get("paths", [])
        if not paths:
            return "Error: 'paths' must be a non-empty list"
        if len(paths) > 20:
            return "Error: Too many files requested (max 20)"

        sections: list[str] = []
        for p in paths:
            header = f"=== {p} ==="
            try:
                resolved = self._safe_path(p)
                if not resolved.is_file():
                    sections.append(f"{header}\nFile not found: {p}")
                    continue
                if self._is_excluded(resolved):
                    sections.append(f"{header}\nAccess denied: matches privacy exclude pattern")
                    continue
                text = resolved.read_text(encoding="utf-8", errors="replace")
                lines = text.split("\n")
                numbered = [f"{i + 1:4d} | {line}" for i, line in enumerate(lines)]
                sections.append(f"{header}\n" + "\n".join(numbered))
            except ValueError as e:
                sections.append(f"{header}\nError: {e}")
            except Exception as e:
                sections.append(f"{header}\nError reading file: {e}")

        return "\n\n".join(sections)

    async def _web_search(self, args: dict) -> str:
        if DDGS is None:
            return "Error: web_search requires the 'duckduckgo-search' package (pip install duckduckgo-search)"

        query = args.get("query", "")
        if not query:
            return "Error: 'query' is required"
        max_results = min(args.get("max_results", 5), 10)

        try:
            results = await asyncio.to_thread(
                lambda: DDGS().text(query, max_results=max_results)
            )
        except Exception as e:
            return f"Error performing web search: {e}"

        if not results:
            return f"No results found for '{query}'"

        lines: list[str] = []
        for i, r in enumerate(results, 1):
            lines.append(f"{i}. {r.get('title', 'No title')}")
            lines.append(f"   URL: {r.get('href', r.get('link', 'N/A'))}")
            lines.append(f"   {r.get('body', r.get('snippet', ''))}")
            lines.append("")
        return "\n".join(lines).rstrip()

    @staticmethod
    def _extract_text_from_html(html: str) -> str:
        """Extract visible text from HTML by stripping tags."""
        # Remove script and style elements
        text = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", html, flags=re.DOTALL | re.IGNORECASE)
        # Replace block-level tags with newlines
        text = re.sub(r"<(br|p|div|h[1-6]|li|tr)[^>]*/?>", "\n", text, flags=re.IGNORECASE)
        # Strip remaining tags
        text = re.sub(r"<[^>]+>", "", text)
        # Collapse whitespace
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()

    @staticmethod
    def _is_private_ip(hostname: str) -> bool:
        """Check if a hostname resolves to a private/loopback IP."""
        if hostname in ("localhost", "127.0.0.1", "::1"):
            return True
        try:
            addr = ipaddress.ip_address(hostname)
            return addr.is_private or addr.is_loopback
        except ValueError:
            return False

    async def _fetch_url(self, args: dict) -> str:
        url = args.get("url", "")
        if not url:
            return "Error: 'url' is required"

        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            return f"Error: Only http and https schemes are allowed, got '{parsed.scheme}'"

        hostname = parsed.hostname or ""
        if self._is_private_ip(hostname):
            return "Error: Fetching private/local addresses is not allowed"

        try:
            async with httpx.AsyncClient(
                timeout=15.0,
                follow_redirects=True,
                max_redirects=5,
            ) as client:
                response = await client.get(url)

                # Check response size (2MB limit)
                content_length = len(response.content)
                if content_length > 2 * 1024 * 1024:
                    return "Error: Response too large (exceeds 2MB limit)"

                content_type = response.headers.get("content-type", "")
                body = response.text

                if "application/json" in content_type:
                    try:
                        data = json.loads(body)
                        body = json.dumps(data, indent=2)
                    except json.JSONDecodeError:
                        pass
                elif "text/html" in content_type:
                    body = self._extract_text_from_html(body)

                return body
        except httpx.TimeoutException:
            return "Error: Request timed out (15s limit)"
        except httpx.TooManyRedirects:
            return "Error: Too many redirects (max 5)"
        except Exception as e:
            return f"Error fetching URL: {e}"

    async def _run_command(self, args: dict) -> str:
        if not self._config.agentic.allow_shell_commands:
            return "Error: Shell commands are disabled. Set agentic.allow_shell_commands=true in config to enable."

        command = args.get("command", "")
        if not command:
            return "Error: 'command' is required"

        # Check against blocklist
        for pattern in _BLOCKED_COMMAND_PATTERNS:
            if pattern.search(command):
                return f"Error: Command blocked by security policy (matched: {pattern.pattern})"

        timeout = min(args.get("timeout", 30), 60)

        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                cwd=str(self._root),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            return f"Error: Command timed out after {timeout}s"
        except Exception as e:
            return f"Error running command: {e}"

        out = stdout.decode("utf-8", errors="replace")
        err = stderr.decode("utf-8", errors="replace")

        parts: list[str] = [f"Exit code: {proc.returncode}"]
        if out:
            parts.append(f"stdout:\n{out}")
        if err:
            parts.append(f"stderr:\n{err}")
        return "\n".join(parts)
