"""Context assembly with token-budgeted priority waterfall."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path

import litellm

from codesage.config import ContextConfig
from codesage.indexer.index import SymbolIndex
from codesage.indexer.project import get_git_diff

logger = logging.getLogger(__name__)


def _count_tokens(text: str, model: str) -> int:
    """Count tokens in text using litellm's token counter."""
    try:
        return litellm.token_counter(model=model, text=text)
    except Exception:
        # Rough fallback: ~4 chars per token
        return len(text) // 4


@dataclass
class AssembledContext:
    """Result of context assembly with rendered sections."""

    selected_code: str = ""
    file_context: str = ""
    project_summary: str = ""
    git_diff: str = ""
    import_context: str = ""
    related_symbols: str = ""
    total_tokens: int = 0

    def render(self) -> str:
        """Render all context sections into a single string."""
        parts: list[str] = []

        if self.project_summary:
            parts.append("## Project Context")
            parts.append(self.project_summary)
            parts.append("")

        if self.git_diff:
            parts.append("## Recent Changes")
            parts.append(self.git_diff)
            parts.append("")

        if self.file_context:
            parts.append("## Current File Context")
            parts.append(self.file_context)
            parts.append("")

        if self.import_context:
            parts.append("## Imported Symbols")
            parts.append(self.import_context)
            parts.append("")

        if self.related_symbols:
            parts.append("## Related Definitions")
            parts.append(self.related_symbols)
            parts.append("")

        return "\n".join(parts)


class ContextAssembler:
    """Assembles token-budgeted context from project index.

    Priority waterfall within max_context_tokens:
    1. Selected code (always included)
    2. Immediate file context (30%): full file or window around selection + imports
    3. Project summary (5%): compact tree + language stats
    4. Import resolution (25%): signatures of imported modules' public symbols
    5. Related symbols (25%): definitions of referenced functions/classes
    6. Reserve (15%): for prompt template overhead
    """

    def __init__(
        self,
        index: SymbolIndex,
        config: ContextConfig,
        model: str = "",
        project_root: Path | None = None,
    ) -> None:
        self._index = index
        self._config = config
        self._model = model or "gpt-4o-mini"
        self._project_root = project_root

    def _tokens(self, text: str) -> int:
        return _count_tokens(text, self._model)

    def assemble(
        self,
        code: str,
        filepath: str = "",
        file_content: str = "",
        language: str = "",
        **kwargs: object,
    ) -> AssembledContext:
        """Assemble context with token budget management.

        Args:
            code: The selected code snippet.
            filepath: Absolute path to the current file.
            file_content: Full content of the current file.
            language: Language of the code.

        Returns:
            AssembledContext with populated sections.
        """
        max_tokens = self._config.max_context_tokens
        # Reserve 15% for prompt overhead
        available = int(max_tokens * 0.85)

        result = AssembledContext(selected_code=code)

        # Selected code always included — subtract from budget
        code_tokens = self._tokens(code)
        available -= code_tokens

        if available <= 0:
            result.total_tokens = code_tokens
            return result

        # Budget allocations for remaining space
        file_budget = int(available * 0.30)
        summary_budget = int(available * 0.05)
        git_diff_budget = int(available * 0.10)
        import_budget = int(available * 0.27)
        related_budget = int(available * 0.28)

        total_tokens = code_tokens

        # 1. File context
        if filepath and file_content:
            file_ctx = self._build_file_context(code, file_content, filepath, file_budget)
            if file_ctx:
                result.file_context = file_ctx
                total_tokens += self._tokens(file_ctx)

        # 2. Project summary
        if self._config.include_project_summary and self._index.project_info:
            summary = self._index.project_info.summary()
            summary_tokens = self._tokens(summary)
            if summary_tokens <= summary_budget:
                result.project_summary = summary
                total_tokens += summary_tokens

        # 3. Git diff context
        if self._config.include_git_diff and self._project_root:
            diff_text = get_git_diff(self._project_root)
            if diff_text:
                diff_tokens = self._tokens(diff_text)
                if diff_tokens > git_diff_budget:
                    # Truncate to fit budget (rough char estimate)
                    char_limit = git_diff_budget * 4
                    diff_text = diff_text[:char_limit] + "\n... (truncated)"
                result.git_diff = diff_text
                total_tokens += self._tokens(diff_text)

        # 4. Import resolution
        if self._config.include_imports and filepath:
            import_ctx = self._build_import_context(Path(filepath), import_budget)
            if import_ctx:
                result.import_context = import_ctx
                total_tokens += self._tokens(import_ctx)

        # 5. Related symbols
        if self._config.include_related_symbols:
            related = self._build_related_symbols(code, filepath, related_budget)
            if related:
                result.related_symbols = related
                total_tokens += self._tokens(related)

        result.total_tokens = total_tokens
        return result

    def _build_file_context(
        self, code: str, file_content: str, filepath: str, budget: int
    ) -> str:
        """Build file context: full file or window around selection."""
        # If file fits in budget, include it all
        full_tokens = self._tokens(file_content)
        if full_tokens <= budget:
            return f"Full file `{Path(filepath).name}`:\n```\n{file_content}\n```"

        # Otherwise, build a window around the selection
        lines = file_content.split("\n")
        code_lines = code.split("\n")

        # Find the selection in the file
        try:
            first_code_line = code_lines[0].strip()
            start_idx = None
            for i, line in enumerate(lines):
                if line.strip() == first_code_line:
                    start_idx = i
                    break
        except (IndexError, ValueError):
            start_idx = None

        if start_idx is None:
            # Can't find selection, include top of file
            max_lines = budget // 3  # rough estimate
            truncated = "\n".join(lines[:max_lines])
            return f"File `{Path(filepath).name}` (truncated):\n```\n{truncated}\n```"

        # Window: imports + context around selection
        window_parts: list[str] = []

        # Always include imports (first N lines typically)
        import_lines: list[str] = []
        for line in lines[:min(30, start_idx)]:
            stripped = line.strip()
            if stripped.startswith(("import ", "from ", "#include", "use ", "require", "package ")):
                import_lines.append(line)

        if import_lines:
            window_parts.append("Imports:\n" + "\n".join(import_lines))

        # Context window around selection
        context_radius = 20
        window_start = max(0, start_idx - context_radius)
        window_end = min(len(lines), start_idx + len(code_lines) + context_radius)
        window_text = "\n".join(lines[window_start:window_end])

        # Trim to budget
        while self._tokens("\n".join(window_parts) + "\n" + window_text) > budget and context_radius > 5:
            context_radius -= 5
            window_start = max(0, start_idx - context_radius)
            window_end = min(len(lines), start_idx + len(code_lines) + context_radius)
            window_text = "\n".join(lines[window_start:window_end])

        window_parts.append(
            f"Context around selection (lines {window_start + 1}-{window_end}):\n"
            f"```\n{window_text}\n```"
        )

        return "\n\n".join(window_parts)

    def _build_import_context(self, filepath: Path, budget: int) -> str:
        """Resolve imports and include signatures of imported symbols."""
        imports = self._index.get_imports(filepath)
        if not imports:
            return ""

        parts: list[str] = []
        current_tokens = 0

        for imp in imports:
            # Extract imported names from import statements
            names = self._extract_import_names(imp.signature)
            for name in names:
                # Look up the symbol in the index
                definitions = self._index.lookup(name)
                for defn in definitions:
                    if defn.kind == "import":
                        continue
                    entry = f"- `{defn.signature}` ({defn.kind} in {Path(defn.file).name}:{defn.line})"
                    entry_tokens = self._tokens(entry)
                    if current_tokens + entry_tokens > budget:
                        return "\n".join(parts)
                    parts.append(entry)
                    current_tokens += entry_tokens

        return "\n".join(parts)

    def _extract_import_names(self, import_sig: str) -> list[str]:
        """Extract imported symbol names from an import statement."""
        names: list[str] = []

        # Python: from X import a, b, c  or  import X
        match = re.match(r"from\s+\S+\s+import\s+(.+)", import_sig)
        if match:
            for name in match.group(1).split(","):
                name = name.strip()
                # Handle 'as' aliases
                if " as " in name:
                    name = name.split(" as ")[0].strip()
                if name and name != "*":
                    names.append(name)
            return names

        match = re.match(r"import\s+(.+)", import_sig)
        if match:
            for name in match.group(1).split(","):
                name = name.strip()
                if " as " in name:
                    name = name.split(" as ")[0].strip()
                # For 'import foo.bar', use 'bar'
                if "." in name:
                    name = name.split(".")[-1]
                if name:
                    names.append(name)

        return names

    def _build_related_symbols(self, code: str, filepath: str, budget: int) -> str:
        """Find and include definitions of symbols referenced in the code."""
        # Extract potential symbol references (identifiers) from the code
        identifiers = set(re.findall(r"\b([A-Za-z_]\w*)\b", code))
        # Remove common keywords
        keywords = {
            "def", "class", "return", "if", "else", "elif", "for", "while", "import",
            "from", "in", "is", "not", "and", "or", "True", "False", "None", "self",
            "with", "as", "try", "except", "finally", "raise", "yield", "async", "await",
            "pass", "break", "continue", "lambda", "global", "nonlocal", "assert", "del",
            "var", "let", "const", "function", "new", "this", "typeof", "instanceof",
            "void", "null", "undefined", "true", "false", "int", "str", "float", "bool",
            "list", "dict", "set", "tuple", "print", "len", "range", "enumerate", "super",
        }
        identifiers -= keywords

        parts: list[str] = []
        current_tokens = 0
        seen_sigs: set[str] = set()

        for ident in sorted(identifiers):
            definitions = self._index.lookup(ident)
            for defn in definitions:
                if defn.kind == "import":
                    continue
                # Don't include definitions from the current file
                if filepath and defn.file == str(Path(filepath).resolve()):
                    continue
                if defn.signature in seen_sigs:
                    continue
                seen_sigs.add(defn.signature)

                entry = f"- `{defn.signature}` ({defn.kind} in {Path(defn.file).name}:{defn.line})"
                entry_tokens = self._tokens(entry)
                if current_tokens + entry_tokens > budget:
                    return "\n".join(parts)
                parts.append(entry)
                current_tokens += entry_tokens

        return "\n".join(parts)
