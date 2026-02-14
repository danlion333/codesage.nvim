"""Tests for SymbolExtractor."""

from __future__ import annotations

from pathlib import Path

import pytest

from codesage.indexer.symbols import Symbol, SymbolExtractor


@pytest.fixture
def extractor() -> SymbolExtractor:
    return SymbolExtractor()


class TestPythonExtraction:
    def test_function(self, extractor: SymbolExtractor):
        code = "def hello(name: str) -> str:\n    return f'hello {name}'"
        symbols = extractor.extract(code, "python")
        funcs = [s for s in symbols if s.kind == "function"]
        assert len(funcs) == 1
        assert funcs[0].name == "hello"
        assert "def hello" in funcs[0].signature

    def test_class(self, extractor: SymbolExtractor):
        code = "class MyClass:\n    pass"
        symbols = extractor.extract(code, "python")
        classes = [s for s in symbols if s.kind == "class"]
        assert len(classes) == 1
        assert classes[0].name == "MyClass"

    def test_class_with_methods(self, extractor: SymbolExtractor):
        code = (
            "class Foo:\n"
            "    def bar(self):\n"
            "        pass\n"
            "    def baz(self, x):\n"
            "        return x\n"
        )
        symbols = extractor.extract(code, "python")
        funcs = [s for s in symbols if s.kind == "function"]
        classes = [s for s in symbols if s.kind == "class"]
        assert len(classes) == 1
        # In Python, tree-sitter sees methods as function_definitions
        assert len(funcs) >= 2

    def test_imports(self, extractor: SymbolExtractor):
        code = "import os\nfrom pathlib import Path\n"
        symbols = extractor.extract(code, "python")
        imports = [s for s in symbols if s.kind == "import"]
        assert len(imports) == 2

    def test_empty_file(self, extractor: SymbolExtractor):
        symbols = extractor.extract("", "python")
        assert symbols == []

    def test_syntax_error(self, extractor: SymbolExtractor):
        code = "def broken(:\n    ///invalid"
        # Should not crash, may return partial results or empty
        symbols = extractor.extract(code, "python")
        assert isinstance(symbols, list)

    def test_line_numbers(self, extractor: SymbolExtractor):
        code = "# comment\ndef foo():\n    pass\n\ndef bar():\n    pass"
        symbols = extractor.extract(code, "python")
        funcs = [s for s in symbols if s.kind == "function"]
        assert len(funcs) == 2
        assert funcs[0].line == 2
        assert funcs[1].line == 5


class TestJavaScriptExtraction:
    def test_function_declaration(self, extractor: SymbolExtractor):
        code = "function greet(name) {\n  return `hello ${name}`;\n}"
        symbols = extractor.extract(code, "javascript")
        funcs = [s for s in symbols if s.kind == "function"]
        assert len(funcs) == 1
        assert funcs[0].name == "greet"

    def test_class(self, extractor: SymbolExtractor):
        code = "class Animal {\n  constructor(name) {\n    this.name = name;\n  }\n}"
        symbols = extractor.extract(code, "javascript")
        classes = [s for s in symbols if s.kind == "class"]
        assert len(classes) == 1
        assert classes[0].name == "Animal"

    def test_imports(self, extractor: SymbolExtractor):
        code = "import { foo } from './bar';"
        symbols = extractor.extract(code, "javascript")
        imports = [s for s in symbols if s.kind == "import"]
        assert len(imports) == 1


class TestGoExtraction:
    def test_function(self, extractor: SymbolExtractor):
        code = "package main\n\nfunc main() {\n\tfmt.Println(\"hello\")\n}"
        symbols = extractor.extract(code, "go")
        funcs = [s for s in symbols if s.kind == "function"]
        assert len(funcs) == 1
        assert funcs[0].name == "main"

    def test_struct(self, extractor: SymbolExtractor):
        code = "package main\n\ntype Server struct {\n\tPort int\n}"
        symbols = extractor.extract(code, "go")
        classes = [s for s in symbols if s.kind == "class"]
        assert len(classes) == 1
        assert classes[0].name == "Server"


class TestRustExtraction:
    def test_function(self, extractor: SymbolExtractor):
        code = "fn main() {\n    println!(\"hello\");\n}"
        symbols = extractor.extract(code, "rust")
        funcs = [s for s in symbols if s.kind == "function"]
        assert len(funcs) == 1
        assert funcs[0].name == "main"

    def test_struct(self, extractor: SymbolExtractor):
        code = "struct Point {\n    x: f64,\n    y: f64,\n}"
        symbols = extractor.extract(code, "rust")
        classes = [s for s in symbols if s.kind == "class"]
        assert len(classes) == 1
        assert classes[0].name == "Point"


class TestUnsupportedLanguage:
    def test_returns_empty(self, extractor: SymbolExtractor):
        symbols = extractor.extract("some code", "brainfuck")
        assert symbols == []


class TestExtractFile:
    def test_extracts_from_file(self, extractor: SymbolExtractor, tmp_path: Path):
        py_file = tmp_path / "example.py"
        py_file.write_text("def foo():\n    pass\n\nclass Bar:\n    pass\n")

        symbols = extractor.extract_file(py_file)

        assert len(symbols) >= 2
        funcs = [s for s in symbols if s.kind == "function"]
        classes = [s for s in symbols if s.kind == "class"]
        assert len(funcs) == 1
        assert len(classes) == 1
        assert all(s.file == str(py_file) for s in symbols)

    def test_auto_detects_language(self, extractor: SymbolExtractor, tmp_path: Path):
        js_file = tmp_path / "app.js"
        js_file.write_text("function hello() {}\n")

        symbols = extractor.extract_file(js_file)
        assert len(symbols) >= 1

    def test_nonexistent_file(self, extractor: SymbolExtractor, tmp_path: Path):
        symbols = extractor.extract_file(tmp_path / "nope.py")
        assert symbols == []
