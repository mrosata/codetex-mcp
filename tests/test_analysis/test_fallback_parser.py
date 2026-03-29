"""Tests for the fallback regex-based parser."""

from __future__ import annotations

import tiktoken

from codetex_mcp.analysis.fallback_parser import FallbackParser


class TestPythonFunctionExtraction:
    def test_simple_function(self) -> None:
        content = "def hello():\n    pass\n"
        parser = FallbackParser()
        result = parser.parse(content, "python")
        assert len(result.symbols) == 1
        sym = result.symbols[0]
        assert sym.name == "hello"
        assert sym.kind == "function"
        assert sym.start_line == 1

    def test_function_with_params_and_return(self) -> None:
        content = "def add(x: int, y: int) -> int:\n    return x + y\n"
        parser = FallbackParser()
        result = parser.parse(content, "python")
        assert len(result.symbols) == 1
        sym = result.symbols[0]
        assert sym.name == "add"
        assert sym.signature == "def add(x: int, y: int) -> int"
        assert len(sym.parameters) == 2
        assert sym.parameters[0].name == "x"
        assert sym.parameters[0].type_annotation == "int"
        assert sym.parameters[1].name == "y"
        assert sym.return_type == "int"

    def test_function_with_default_params(self) -> None:
        content = 'def greet(name: str = "world"):\n    pass\n'
        parser = FallbackParser()
        result = parser.parse(content, "python")
        sym = result.symbols[0]
        assert sym.parameters[0].name == "name"
        assert sym.parameters[0].type_annotation == "str"
        assert sym.parameters[0].default_value == '"world"'

    def test_class_extraction(self) -> None:
        content = "class MyClass(Base):\n    pass\n"
        parser = FallbackParser()
        result = parser.parse(content, "python")
        assert len(result.symbols) == 1
        sym = result.symbols[0]
        assert sym.name == "MyClass"
        assert sym.kind == "class"

    def test_multiple_symbols(self) -> None:
        content = (
            "class Foo:\n"
            "    def bar(self):\n"
            "        pass\n"
            "\n"
            "def baz():\n"
            "    pass\n"
        )
        parser = FallbackParser()
        result = parser.parse(content, "python")
        names = [s.name for s in result.symbols]
        assert "Foo" in names
        assert "bar" in names
        assert "baz" in names

    def test_self_and_cls_excluded_from_params(self) -> None:
        content = "def method(self, x: int):\n    pass\n"
        parser = FallbackParser()
        result = parser.parse(content, "python")
        sym = result.symbols[0]
        assert len(sym.parameters) == 1
        assert sym.parameters[0].name == "x"

    def test_docstring_extraction(self) -> None:
        content = 'def foo():\n    """This is a docstring."""\n    pass\n'
        parser = FallbackParser()
        result = parser.parse(content, "python")
        sym = result.symbols[0]
        assert sym.docstring == "This is a docstring."

    def test_end_line_estimation(self) -> None:
        content = (
            "def foo():\n"
            "    x = 1\n"
            "    y = 2\n"
            "    return x + y\n"
            "\n"
            "def bar():\n"
            "    pass\n"
        )
        parser = FallbackParser()
        result = parser.parse(content, "python")
        foo = result.symbols[0]
        assert foo.name == "foo"
        assert foo.start_line == 1
        # end_line should be before bar's definition
        assert foo.end_line <= 6


class TestJavaScriptFunctionExtraction:
    def test_simple_function(self) -> None:
        content = "function hello() {\n    console.log('hi');\n}\n"
        parser = FallbackParser()
        result = parser.parse(content, "javascript")
        assert len(result.symbols) == 1
        sym = result.symbols[0]
        assert sym.name == "hello"
        assert sym.kind == "function"

    def test_async_function(self) -> None:
        content = "async function fetchData(url) {\n    return await fetch(url);\n}\n"
        parser = FallbackParser()
        result = parser.parse(content, "javascript")
        assert len(result.symbols) == 1
        assert result.symbols[0].name == "fetchData"

    def test_export_function(self) -> None:
        content = "export function helper() {\n    return true;\n}\n"
        parser = FallbackParser()
        result = parser.parse(content, "javascript")
        assert len(result.symbols) == 1
        assert result.symbols[0].name == "helper"

    def test_class_extraction(self) -> None:
        content = "class Widget extends Component {\n    render() {}\n}\n"
        parser = FallbackParser()
        result = parser.parse(content, "javascript")
        assert len(result.symbols) >= 1
        classes = [s for s in result.symbols if s.kind == "class"]
        assert len(classes) == 1
        assert classes[0].name == "Widget"

    def test_export_class(self) -> None:
        content = "export class MyService {\n    start() {}\n}\n"
        parser = FallbackParser()
        result = parser.parse(content, "javascript")
        classes = [s for s in result.symbols if s.kind == "class"]
        assert len(classes) == 1
        assert classes[0].name == "MyService"


class TestGoFunctionExtraction:
    def test_simple_function(self) -> None:
        content = "func main() {\n    fmt.Println(\"hello\")\n}\n"
        parser = FallbackParser()
        result = parser.parse(content, "go")
        assert len(result.symbols) == 1
        assert result.symbols[0].name == "main"

    def test_function_with_return(self) -> None:
        content = "func add(a int, b int) int {\n    return a + b\n}\n"
        parser = FallbackParser()
        result = parser.parse(content, "go")
        sym = result.symbols[0]
        assert sym.name == "add"
        assert sym.return_type is not None

    def test_method(self) -> None:
        content = "func (s *Server) Start() error {\n    return nil\n}\n"
        parser = FallbackParser()
        result = parser.parse(content, "go")
        assert len(result.symbols) == 1
        assert result.symbols[0].name == "Start"


class TestRustFunctionExtraction:
    def test_simple_function(self) -> None:
        content = "fn main() {\n    println!(\"hello\");\n}\n"
        parser = FallbackParser()
        result = parser.parse(content, "rust")
        assert len(result.symbols) == 1
        assert result.symbols[0].name == "main"

    def test_pub_function_with_return(self) -> None:
        content = "pub fn add(a: i32, b: i32) -> i32 {\n    a + b\n}\n"
        parser = FallbackParser()
        result = parser.parse(content, "rust")
        sym = result.symbols[0]
        assert sym.name == "add"
        assert sym.return_type is not None

    def test_struct_extraction(self) -> None:
        content = "pub struct Config {\n    pub name: String,\n}\n"
        parser = FallbackParser()
        result = parser.parse(content, "rust")
        assert len(result.symbols) == 1
        assert result.symbols[0].name == "Config"
        assert result.symbols[0].kind == "class"


class TestImportExtraction:
    def test_python_import(self) -> None:
        content = "import os\nimport sys\n"
        parser = FallbackParser()
        result = parser.parse(content, "python")
        assert len(result.imports) == 2
        assert result.imports[0].module == "os"
        assert result.imports[1].module == "sys"

    def test_python_from_import(self) -> None:
        content = "from os.path import join, exists\n"
        parser = FallbackParser()
        result = parser.parse(content, "python")
        assert len(result.imports) == 1
        assert result.imports[0].module == "os.path"
        assert result.imports[0].names == ["join", "exists"]

    def test_javascript_import(self) -> None:
        content = "import { useState, useEffect } from 'react';\n"
        parser = FallbackParser()
        result = parser.parse(content, "javascript")
        assert len(result.imports) == 1
        assert result.imports[0].module == "react"
        assert "useState" in result.imports[0].names
        assert "useEffect" in result.imports[0].names

    def test_javascript_require(self) -> None:
        content = "const express = require('express');\n"
        parser = FallbackParser()
        result = parser.parse(content, "javascript")
        assert len(result.imports) == 1
        assert result.imports[0].module == "express"

    def test_go_import(self) -> None:
        content = 'import "fmt"\n'
        parser = FallbackParser()
        result = parser.parse(content, "go")
        assert len(result.imports) == 1
        assert result.imports[0].module == "fmt"

    def test_rust_use(self) -> None:
        content = "use std::collections::HashMap;\n"
        parser = FallbackParser()
        result = parser.parse(content, "rust")
        assert len(result.imports) == 1
        assert result.imports[0].module == "std::collections::HashMap"

    def test_c_include(self) -> None:
        content = '#include <stdio.h>\n#include "myheader.h"\n'
        parser = FallbackParser()
        result = parser.parse(content, "c")
        assert len(result.imports) == 2
        assert result.imports[0].module == "stdio.h"
        assert result.imports[1].module == "myheader.h"

    def test_ruby_require(self) -> None:
        content = "require 'json'\nrequire_relative 'helper'\n"
        parser = FallbackParser()
        result = parser.parse(content, "ruby")
        assert len(result.imports) == 2
        assert result.imports[0].module == "json"
        assert result.imports[1].module == "helper"

    def test_java_import(self) -> None:
        content = "import java.util.List;\nimport static java.lang.Math.PI;\n"
        parser = FallbackParser()
        result = parser.parse(content, "java")
        assert len(result.imports) == 2
        assert result.imports[0].module == "java.util.List"
        assert result.imports[1].module == "java.lang.Math.PI"


class TestLineCount:
    def test_counts_all_lines(self) -> None:
        content = "line1\nline2\nline3\n"
        parser = FallbackParser()
        result = parser.parse(content, None)
        assert result.lines_of_code == 3

    def test_empty_content(self) -> None:
        parser = FallbackParser()
        result = parser.parse("", None)
        assert result.lines_of_code == 0

    def test_single_line_no_newline(self) -> None:
        parser = FallbackParser()
        result = parser.parse("x = 1", None)
        assert result.lines_of_code == 1


class TestTokenCount:
    def test_token_count_nonzero(self) -> None:
        content = "def hello():\n    print('Hello, world!')\n"
        parser = FallbackParser()
        result = parser.parse(content, "python")
        assert result.token_count > 0

    def test_token_count_matches_tiktoken(self) -> None:
        content = "function add(a, b) { return a + b; }"
        enc = tiktoken.get_encoding("cl100k_base")
        expected = len(enc.encode(content))
        parser = FallbackParser()
        result = parser.parse(content, "javascript")
        assert result.token_count == expected

    def test_empty_content_zero_tokens(self) -> None:
        parser = FallbackParser()
        result = parser.parse("", None)
        assert result.token_count == 0


class TestLanguageNone:
    def test_unknown_language_still_parses(self) -> None:
        content = "def foo():\n    pass\n"
        parser = FallbackParser()
        result = parser.parse(content, None)
        assert result.language is None
        # Python patterns should still match even without language hint
        assert len(result.symbols) == 1
        assert result.symbols[0].name == "foo"

    def test_path_set_to_empty(self) -> None:
        parser = FallbackParser()
        result = parser.parse("x = 1", None)
        assert result.path == ""


class TestMixedContent:
    def test_file_with_imports_and_functions(self) -> None:
        content = (
            "import os\n"
            "from pathlib import Path\n"
            "\n"
            "def process(path: Path) -> bool:\n"
            '    """Process a file."""\n'
            "    return path.exists()\n"
            "\n"
            "class Handler:\n"
            "    def handle(self):\n"
            "        pass\n"
        )
        parser = FallbackParser()
        result = parser.parse(content, "python")
        assert len(result.imports) == 2
        assert len(result.symbols) == 3  # process, Handler, handle
        assert result.lines_of_code == 10
        assert result.token_count > 0

        # Check the function details
        process = next(s for s in result.symbols if s.name == "process")
        assert process.kind == "function"
        assert process.return_type == "bool"
        assert process.docstring == "Process a file."
        assert len(process.parameters) == 1
        assert process.parameters[0].name == "path"
        assert process.parameters[0].type_annotation == "Path"
