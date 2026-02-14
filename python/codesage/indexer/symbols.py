"""Symbol extraction using tree-sitter."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

import tree_sitter_languages

logger = logging.getLogger(__name__)


@dataclass
class Symbol:
    """A code symbol (function, class, variable, etc.)."""

    name: str = ""
    kind: str = ""  # function, class, method, import
    file: str = ""
    line: int = 0
    end_line: int = 0
    signature: str = ""
    parent: str = ""


# Maps our language names to tree-sitter-languages grammar names
LANGUAGE_GRAMMAR_MAP: dict[str, str] = {
    "python": "python",
    "javascript": "javascript",
    "typescript": "typescript",
    "tsx": "tsx",
    "go": "go",
    "rust": "rust",
    "java": "java",
    "c": "c",
    "cpp": "cpp",
    "lua": "lua",
    "ruby": "ruby",
}

# Tree-sitter S-expression queries per language
LANGUAGE_QUERIES: dict[str, str] = {
    "python": """
        (function_definition
            name: (identifier) @func.name) @func.def

        (class_definition
            name: (identifier) @class.name) @class.def

        (import_statement) @import

        (import_from_statement) @import
    """,
    "javascript": """
        (function_declaration
            name: (identifier) @func.name) @func.def

        (class_declaration
            name: (identifier) @class.name) @class.def

        (method_definition
            name: (property_identifier) @method.name) @method.def

        (lexical_declaration
            (variable_declarator
                name: (identifier) @func.name
                value: (arrow_function))) @func.def

        (import_statement) @import
    """,
    "typescript": """
        (function_declaration
            name: (identifier) @func.name) @func.def

        (class_declaration
            name: (type_identifier) @class.name) @class.def

        (method_definition
            name: (property_identifier) @method.name) @method.def

        (lexical_declaration
            (variable_declarator
                name: (identifier) @func.name
                value: (arrow_function))) @func.def

        (import_statement) @import

        (interface_declaration
            name: (type_identifier) @class.name) @class.def

        (type_alias_declaration
            name: (type_identifier) @class.name) @class.def
    """,
    "go": """
        (function_declaration
            name: (identifier) @func.name) @func.def

        (method_declaration
            name: (field_identifier) @method.name) @method.def

        (type_declaration
            (type_spec
                name: (type_identifier) @class.name)) @class.def

        (import_declaration) @import
    """,
    "rust": """
        (function_item
            name: (identifier) @func.name) @func.def

        (struct_item
            name: (type_identifier) @class.name) @class.def

        (enum_item
            name: (type_identifier) @class.name) @class.def

        (impl_item
            type: (type_identifier) @class.name) @class.def

        (trait_item
            name: (type_identifier) @class.name) @class.def

        (use_declaration) @import
    """,
    "java": """
        (method_declaration
            name: (identifier) @func.name) @func.def

        (class_declaration
            name: (identifier) @class.name) @class.def

        (interface_declaration
            name: (identifier) @class.name) @class.def

        (import_declaration) @import
    """,
    "c": """
        (function_definition
            declarator: (function_declarator
                declarator: (identifier) @func.name)) @func.def

        (struct_specifier
            name: (type_identifier) @class.name) @class.def

        (preproc_include) @import
    """,
    "cpp": """
        (function_definition
            declarator: (function_declarator
                declarator: (identifier) @func.name)) @func.def

        (function_definition
            declarator: (function_declarator
                declarator: (qualified_identifier) @func.name)) @func.def

        (class_specifier
            name: (type_identifier) @class.name) @class.def

        (struct_specifier
            name: (type_identifier) @class.name) @class.def

        (preproc_include) @import
    """,
    "lua": """
        (function_declaration
            name: (identifier) @func.name) @func.def

        (function_declaration
            name: (dot_index_expression) @func.name) @func.def
    """,
}


def _get_node_text(node: object, source: bytes) -> str:
    """Extract text from a tree-sitter node."""
    return source[node.start_byte:node.end_byte].decode("utf-8", errors="replace")


def _get_signature(node: object, source: bytes, max_len: int = 200) -> str:
    """Extract a compact signature from a definition node."""
    text = _get_node_text(node, source)
    # Take first line or up to max_len
    first_line = text.split("\n")[0]
    if len(first_line) > max_len:
        return first_line[:max_len] + "..."
    return first_line


class SymbolExtractor:
    """Extracts symbols from source code using tree-sitter."""

    def extract(self, code: str, language: str = "") -> list[Symbol]:
        """Extract symbols from a code string.

        Args:
            code: Source code to parse.
            language: Language identifier (e.g., "python", "javascript").

        Returns:
            List of extracted symbols.
        """
        grammar_name = LANGUAGE_GRAMMAR_MAP.get(language)
        if not grammar_name:
            return []

        query_str = LANGUAGE_QUERIES.get(grammar_name)
        if not query_str:
            return []

        try:
            parser = tree_sitter_languages.get_parser(grammar_name)
            ts_language = tree_sitter_languages.get_language(grammar_name)
        except Exception:
            logger.debug("No tree-sitter grammar for: %s", language)
            return []

        source = code.encode("utf-8")
        try:
            tree = parser.parse(source)
        except Exception:
            logger.debug("Failed to parse %s code", language)
            return []

        try:
            query = ts_language.query(query_str)
        except Exception:
            logger.debug("Failed to compile query for %s", language)
            return []

        symbols: list[Symbol] = []
        captures = query.captures(tree.root_node)

        # Process captures in document order.
        # tree-sitter returns outer nodes first, so the order is:
        #   .def (outer) then .name (inner)
        # We process .def captures and look ahead for the .name.
        i = 0
        while i < len(captures):
            node, capture_name = captures[i]

            if capture_name == "import":
                text = _get_node_text(node, source)
                symbols.append(Symbol(
                    name=text.strip(),
                    kind="import",
                    line=node.start_point[0] + 1,
                    end_line=node.end_point[0] + 1,
                    signature=text.strip().split("\n")[0],
                ))
                i += 1
                continue

            if capture_name in ("func.def", "method.def", "class.def"):
                def_node = node
                sig = _get_signature(def_node, source)
                end_line = def_node.end_point[0] + 1

                kind = "class" if capture_name == "class.def" else (
                    "method" if capture_name == "method.def" else "function"
                )

                # Look ahead for the corresponding .name capture
                name = sig.split("(")[0].split()[-1] if "(" in sig else sig.split()[-1]
                if i + 1 < len(captures):
                    next_node, next_name = captures[i + 1]
                    if next_name in ("func.name", "method.name", "class.name"):
                        name = _get_node_text(next_node, source)
                        i += 1  # skip the .name capture

                # Determine parent (for methods)
                parent = ""
                if kind == "method":
                    p = def_node.parent
                    while p:
                        if p.type in (
                            "class_definition", "class_declaration",
                            "class_specifier", "impl_item",
                        ):
                            for child in p.children:
                                if child.type in ("identifier", "type_identifier"):
                                    parent = _get_node_text(child, source)
                                    break
                            break
                        p = p.parent

                symbols.append(Symbol(
                    name=name,
                    kind=kind,
                    line=def_node.start_point[0] + 1,
                    end_line=end_line,
                    signature=sig,
                    parent=parent,
                ))
                i += 1
                continue

            # Skip orphaned .name captures
            i += 1

        return symbols

    def extract_file(self, path: Path, language: str = "") -> list[Symbol]:
        """Extract symbols from a file.

        Args:
            path: Path to the source file.
            language: Language identifier. Auto-detected from extension if empty.

        Returns:
            List of extracted symbols with file field set.
        """
        from codesage.indexer.project import detect_language

        if not language:
            language = detect_language(path)

        try:
            code = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            logger.debug("Cannot read file: %s", path)
            return []

        symbols = self.extract(code, language)
        for sym in symbols:
            sym.file = str(path)
        return symbols
