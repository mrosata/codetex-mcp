"""Tests for the tree-sitter AST parser."""

from __future__ import annotations

import pytest

from codetex_mcp.analysis.tree_sitter import TreeSitterParser


class TestLanguageSupport:
    def test_python_supported_if_grammar_installed(self) -> None:
        parser = TreeSitterParser()
        # tree-sitter-python is installed as a dev/test dependency
        try:
            import tree_sitter_python  # noqa: F401

            assert parser.is_language_supported("python") is True
        except ImportError:
            assert parser.is_language_supported("python") is False

    def test_unsupported_language(self) -> None:
        parser = TreeSitterParser()
        assert parser.is_language_supported("cobol") is False

    def test_language_result_cached(self) -> None:
        parser = TreeSitterParser()
        _ = parser.is_language_supported("python")
        assert "python" in parser._languages
        # Second call should use cache
        result = parser.is_language_supported("python")
        assert isinstance(result, bool)

    def test_unsupported_language_cached_as_none(self) -> None:
        parser = TreeSitterParser()
        assert parser.is_language_supported("cobol") is False
        assert parser._languages["cobol"] is None


# Skip all Python parsing tests if grammar is not installed
try:
    import tree_sitter_python  # noqa: F401

    _HAS_PYTHON_GRAMMAR = True
except ImportError:
    _HAS_PYTHON_GRAMMAR = False

pytestmark_python = pytest.mark.skipif(
    not _HAS_PYTHON_GRAMMAR, reason="tree-sitter-python not installed"
)


@pytestmark_python
class TestPythonFunctionExtraction:
    def test_simple_function(self) -> None:
        content = "def hello():\n    pass\n"
        parser = TreeSitterParser()
        result = parser.parse(content, "python")
        assert len(result.symbols) == 1
        sym = result.symbols[0]
        assert sym.name == "hello"
        assert sym.kind == "function"
        assert sym.start_line == 1

    def test_function_with_params_and_return(self) -> None:
        content = "def add(x: int, y: int) -> int:\n    return x + y\n"
        parser = TreeSitterParser()
        result = parser.parse(content, "python")
        assert len(result.symbols) == 1
        sym = result.symbols[0]
        assert sym.name == "add"
        assert sym.kind == "function"
        assert len(sym.parameters) == 2
        assert sym.parameters[0].name == "x"
        assert sym.parameters[0].type_annotation == "int"
        assert sym.parameters[1].name == "y"
        assert sym.return_type == "int"
        assert "def add" in sym.signature
        assert "-> int" in sym.signature

    def test_function_with_defaults(self) -> None:
        content = 'def greet(name: str = "world"):\n    pass\n'
        parser = TreeSitterParser()
        result = parser.parse(content, "python")
        sym = result.symbols[0]
        assert sym.parameters[0].name == "name"
        assert sym.parameters[0].type_annotation == "str"
        assert sym.parameters[0].default_value == '"world"'

    def test_self_and_cls_excluded(self) -> None:
        content = "class Foo:\n    def method(self, x: int):\n        pass\n"
        parser = TreeSitterParser()
        result = parser.parse(content, "python")
        method = next(s for s in result.symbols if s.name == "method")
        assert len(method.parameters) == 1
        assert method.parameters[0].name == "x"

    def test_args_and_kwargs(self) -> None:
        content = "def func(*args, **kwargs):\n    pass\n"
        parser = TreeSitterParser()
        result = parser.parse(content, "python")
        sym = result.symbols[0]
        param_names = [p.name for p in sym.parameters]
        assert "args" in param_names
        assert "kwargs" in param_names

    def test_decorated_function(self) -> None:
        content = "@decorator\ndef decorated() -> int:\n    return 1\n"
        parser = TreeSitterParser()
        result = parser.parse(content, "python")
        assert len(result.symbols) == 1
        sym = result.symbols[0]
        assert sym.name == "decorated"
        assert sym.kind == "function"
        assert sym.return_type == "int"


@pytestmark_python
class TestPythonClassExtraction:
    def test_simple_class(self) -> None:
        content = "class MyClass:\n    pass\n"
        parser = TreeSitterParser()
        result = parser.parse(content, "python")
        assert len(result.symbols) == 1
        sym = result.symbols[0]
        assert sym.name == "MyClass"
        assert sym.kind == "class"
        assert sym.signature == "class MyClass"

    def test_class_with_bases(self) -> None:
        content = "class Child(Base, Mixin):\n    pass\n"
        parser = TreeSitterParser()
        result = parser.parse(content, "python")
        sym = result.symbols[0]
        assert sym.name == "Child"
        assert sym.kind == "class"
        assert "Base" in sym.signature
        assert "Mixin" in sym.signature

    def test_class_docstring(self) -> None:
        content = 'class Documented:\n    """This is a class."""\n    pass\n'
        parser = TreeSitterParser()
        result = parser.parse(content, "python")
        sym = result.symbols[0]
        assert sym.docstring == "This is a class."

    def test_class_with_methods(self) -> None:
        content = (
            "class MyClass:\n"
            "    def __init__(self, name: str):\n"
            "        self.name = name\n"
            "\n"
            "    def greet(self) -> str:\n"
            "        return f'Hello, {self.name}'\n"
        )
        parser = TreeSitterParser()
        result = parser.parse(content, "python")
        names = [s.name for s in result.symbols]
        assert "MyClass" in names
        assert "__init__" in names
        assert "greet" in names

        # Methods should have kind "method"
        init = next(s for s in result.symbols if s.name == "__init__")
        assert init.kind == "method"
        greet = next(s for s in result.symbols if s.name == "greet")
        assert greet.kind == "method"
        assert greet.return_type == "str"


@pytestmark_python
class TestPythonDocstringExtraction:
    def test_function_docstring(self) -> None:
        content = 'def foo():\n    """A docstring."""\n    pass\n'
        parser = TreeSitterParser()
        result = parser.parse(content, "python")
        assert result.symbols[0].docstring == "A docstring."

    def test_multiline_docstring(self) -> None:
        content = 'def foo():\n    """First line.\n\n    Details here.\n    """\n    pass\n'
        parser = TreeSitterParser()
        result = parser.parse(content, "python")
        assert result.symbols[0].docstring is not None
        assert "First line." in result.symbols[0].docstring  # type: ignore[operator]

    def test_no_docstring(self) -> None:
        content = "def foo():\n    x = 1\n"
        parser = TreeSitterParser()
        result = parser.parse(content, "python")
        assert result.symbols[0].docstring is None

    def test_single_quoted_docstring(self) -> None:
        content = "def foo():\n    '''A single-quoted docstring.'''\n    pass\n"
        parser = TreeSitterParser()
        result = parser.parse(content, "python")
        assert result.symbols[0].docstring == "A single-quoted docstring."


@pytestmark_python
class TestPythonImportExtraction:
    def test_simple_import(self) -> None:
        content = "import os\nimport sys\n"
        parser = TreeSitterParser()
        result = parser.parse(content, "python")
        assert len(result.imports) == 2
        modules = [i.module for i in result.imports]
        assert "os" in modules
        assert "sys" in modules

    def test_from_import(self) -> None:
        content = "from os.path import join, exists\n"
        parser = TreeSitterParser()
        result = parser.parse(content, "python")
        assert len(result.imports) == 1
        assert result.imports[0].module == "os.path"
        assert "join" in result.imports[0].names
        assert "exists" in result.imports[0].names

    def test_wildcard_import(self) -> None:
        content = "from os import *\n"
        parser = TreeSitterParser()
        result = parser.parse(content, "python")
        assert len(result.imports) == 1
        assert result.imports[0].module == "os"
        assert "*" in result.imports[0].names

    def test_aliased_import(self) -> None:
        content = "import numpy as np\n"
        parser = TreeSitterParser()
        result = parser.parse(content, "python")
        assert len(result.imports) == 1
        assert result.imports[0].module == "numpy"


@pytestmark_python
class TestPythonMetrics:
    def test_line_count(self) -> None:
        content = "def foo():\n    pass\n\ndef bar():\n    pass\n"
        parser = TreeSitterParser()
        result = parser.parse(content, "python")
        assert result.lines_of_code == 5

    def test_token_count(self) -> None:
        content = "def hello():\n    print('Hello, world!')\n"
        parser = TreeSitterParser()
        result = parser.parse(content, "python")
        assert result.token_count > 0

    def test_language_set(self) -> None:
        content = "x = 1\n"
        parser = TreeSitterParser()
        result = parser.parse(content, "python")
        assert result.language == "python"

    def test_path_set_to_empty(self) -> None:
        parser = TreeSitterParser()
        result = parser.parse("x = 1\n", "python")
        assert result.path == ""


@pytestmark_python
class TestPythonFullFile:
    def test_mixed_content(self) -> None:
        content = (
            "import os\n"
            "from pathlib import Path\n"
            "\n"
            "class Handler:\n"
            '    """Handle requests."""\n'
            "\n"
            "    def __init__(self, name: str):\n"
            "        self.name = name\n"
            "\n"
            "    def process(self, data: bytes) -> bool:\n"
            '        """Process incoming data."""\n'
            "        return True\n"
            "\n"
            "def standalone(x: int) -> str:\n"
            "    return str(x)\n"
        )
        parser = TreeSitterParser()
        result = parser.parse(content, "python")

        # Imports
        assert len(result.imports) == 2
        assert result.imports[0].module == "os"
        assert result.imports[1].module == "pathlib"
        assert "Path" in result.imports[1].names

        # Symbols
        names = [s.name for s in result.symbols]
        assert "Handler" in names
        assert "__init__" in names
        assert "process" in names
        assert "standalone" in names

        # Kind detection
        handler = next(s for s in result.symbols if s.name == "Handler")
        assert handler.kind == "class"
        assert handler.docstring == "Handle requests."

        init = next(s for s in result.symbols if s.name == "__init__")
        assert init.kind == "method"

        process = next(s for s in result.symbols if s.name == "process")
        assert process.kind == "method"
        assert process.return_type == "bool"
        assert process.docstring == "Process incoming data."

        standalone = next(s for s in result.symbols if s.name == "standalone")
        assert standalone.kind == "function"
        assert standalone.return_type == "str"

        # Metrics
        assert result.lines_of_code == 15
        assert result.token_count > 0


class TestParseUnsupportedLanguage:
    def test_raises_on_unsupported(self) -> None:
        parser = TreeSitterParser()
        with pytest.raises(ValueError, match="Language not supported"):
            parser.parse("code", "cobol")
