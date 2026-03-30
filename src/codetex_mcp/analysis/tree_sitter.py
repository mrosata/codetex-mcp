"""Tree-sitter AST parser with on-demand grammar loading."""

from __future__ import annotations

import importlib

import tiktoken
import tree_sitter

from codetex_mcp.analysis.models import (
    FileAnalysis,
    ImportInfo,
    ParameterInfo,
    SymbolInfo,
)

# Mapping from language name to tree-sitter grammar package name
_GRAMMAR_PACKAGES: dict[str, str] = {
    "python": "tree_sitter_python",
    "javascript": "tree_sitter_javascript",
    "typescript": "tree_sitter_typescript",
    "go": "tree_sitter_go",
    "rust": "tree_sitter_rust",
    "java": "tree_sitter_java",
    "ruby": "tree_sitter_ruby",
    "cpp": "tree_sitter_cpp",
}

# Lazy-loaded tiktoken encoder
_encoder: tiktoken.Encoding | None = None


def _get_encoder() -> tiktoken.Encoding:
    global _encoder  # noqa: PLW0603
    if _encoder is None:
        _encoder = tiktoken.get_encoding("cl100k_base")
    return _encoder


def _count_tokens(content: str) -> int:
    return len(_get_encoder().encode(content))


def _node_text(node: tree_sitter.Node, source: bytes) -> str:
    """Extract the text of a tree-sitter node."""
    return source[node.start_byte : node.end_byte].decode("utf-8")


class TreeSitterParser:
    """Tree-sitter AST parser with on-demand grammar loading."""

    def __init__(self) -> None:
        # Cache: language name -> Language object or None (if unavailable)
        self._languages: dict[str, tree_sitter.Language | None] = {}

    def _load_language(self, language: str) -> tree_sitter.Language | None:
        """Attempt to load a tree-sitter grammar on demand."""
        if language in self._languages:
            return self._languages[language]

        package_name = _GRAMMAR_PACKAGES.get(language)
        if package_name is None:
            self._languages[language] = None
            return None

        try:
            mod = importlib.import_module(package_name)
            # tree-sitter grammar packages expose a language() function
            language_fn = getattr(mod, "language", None)
            if language_fn is None:
                self._languages[language] = None
                return None
            lang = tree_sitter.Language(language_fn())
            self._languages[language] = lang
            return lang
        except (ImportError, OSError):
            self._languages[language] = None
            return None

    def is_language_supported(self, language: str) -> bool:
        """Check if a tree-sitter grammar is available for the language."""
        return self._load_language(language) is not None

    def parse(self, content: str, language: str) -> FileAnalysis:
        """Parse source content using tree-sitter AST.

        Args:
            content: The source file content.
            language: The detected language name.

        Returns:
            FileAnalysis with extracted symbols, imports, and metrics.
        """
        lang = self._load_language(language)
        if lang is None:
            raise ValueError(f"Language not supported: {language}")

        parser = tree_sitter.Parser(lang)
        source = content.encode("utf-8")
        tree = parser.parse(source)

        symbols = self._extract_symbols(tree.root_node, source, language)
        imports = self._extract_imports(tree.root_node, source, language)
        lines_of_code = len(content.splitlines())
        token_count = _count_tokens(content)

        return FileAnalysis(
            path="",  # Caller sets the actual path
            language=language,
            imports=imports,
            symbols=symbols,
            lines_of_code=lines_of_code,
            token_count=token_count,
        )

    def _extract_symbols(
        self,
        root: tree_sitter.Node,
        source: bytes,
        language: str,
    ) -> list[SymbolInfo]:
        """Extract symbol definitions from the AST."""
        symbols: list[SymbolInfo] = []
        self._walk_for_symbols(root, source, language, symbols, is_method=False)
        return symbols

    def _walk_for_symbols(
        self,
        node: tree_sitter.Node,
        source: bytes,
        language: str,
        symbols: list[SymbolInfo],
        is_method: bool,
    ) -> None:
        """Recursively walk the AST to find symbol definitions."""
        for child in node.children:
            # Handle decorated definitions (Python)
            if child.type == "decorated_definition":
                # The actual definition is a child of the decorated node
                for sub in child.children:
                    if sub.type in ("function_definition", "class_definition"):
                        self._process_symbol_node(
                            sub, source, language, symbols, is_method
                        )
                continue

            if child.type in self._symbol_node_types(language):
                self._process_symbol_node(child, source, language, symbols, is_method)
            elif child.type in ("block", "program", "source_file", "translation_unit"):
                # Recurse into blocks to find nested definitions
                self._walk_for_symbols(child, source, language, symbols, is_method)

    def _symbol_node_types(self, language: str) -> set[str]:
        """Return the AST node types that represent symbol definitions."""
        if language == "python":
            return {"function_definition", "class_definition"}
        if language in ("javascript", "typescript"):
            return {"function_declaration", "class_declaration", "method_definition"}
        if language == "go":
            return {"function_declaration", "method_declaration", "type_declaration"}
        if language == "rust":
            return {
                "function_item",
                "struct_item",
                "enum_item",
                "trait_item",
                "impl_item",
            }
        if language == "java":
            return {"method_declaration", "class_declaration", "interface_declaration"}
        if language == "ruby":
            return {"method", "class", "module"}
        if language == "cpp":
            return {"function_definition", "class_specifier", "struct_specifier"}
        return {"function_definition", "class_definition"}

    def _process_symbol_node(
        self,
        node: tree_sitter.Node,
        source: bytes,
        language: str,
        symbols: list[SymbolInfo],
        is_method: bool,
    ) -> None:
        """Process a single symbol definition AST node."""
        if language == "python":
            self._process_python_symbol(node, source, symbols, is_method)
        else:
            # Generic fallback for other languages
            self._process_generic_symbol(node, source, language, symbols)

    def _process_python_symbol(
        self,
        node: tree_sitter.Node,
        source: bytes,
        symbols: list[SymbolInfo],
        is_method: bool,
    ) -> None:
        """Process a Python function or class definition."""
        name_node = node.child_by_field_name("name")
        if name_node is None:
            return
        name = _node_text(name_node, source)

        if node.type == "function_definition":
            params = self._extract_python_params(node, source)
            return_type = self._extract_python_return_type(node, source)
            docstring = self._extract_python_docstring(node, source)

            # Determine if this is a method (inside a class body)
            kind: str = "method" if is_method else "function"

            # Build signature
            params_node = node.child_by_field_name("parameters")
            params_text = _node_text(params_node, source) if params_node else "()"
            sig = f"def {name}{params_text}"
            if return_type:
                sig += f" -> {return_type}"

            symbols.append(
                SymbolInfo(
                    name=name,
                    kind=kind,  # type: ignore[arg-type]
                    signature=sig,
                    docstring=docstring,
                    start_line=node.start_point[0] + 1,
                    end_line=node.end_point[0] + 1,
                    parameters=params,
                    return_type=return_type,
                    calls=[],
                )
            )

            # Don't recurse into function bodies for nested functions

        elif node.type == "class_definition":
            docstring = self._extract_python_docstring(node, source)
            bases = self._extract_python_bases(node, source)
            sig = f"class {name}"
            if bases:
                sig += f"({', '.join(bases)})"

            symbols.append(
                SymbolInfo(
                    name=name,
                    kind="class",
                    signature=sig,
                    docstring=docstring,
                    start_line=node.start_point[0] + 1,
                    end_line=node.end_point[0] + 1,
                    parameters=[],
                    return_type=None,
                    calls=[],
                )
            )

            # Recurse into class body to find methods
            body = node.child_by_field_name("body")
            if body:
                self._walk_for_symbols(body, source, "python", symbols, is_method=True)

    def _extract_python_params(
        self, func_node: tree_sitter.Node, source: bytes
    ) -> list[ParameterInfo]:
        """Extract parameters from a Python function definition."""
        params: list[ParameterInfo] = []
        params_node = func_node.child_by_field_name("parameters")
        if params_node is None:
            return params

        for child in params_node.children:
            if child.type in ("(", ")", ",", "/"):
                continue

            param = self._parse_python_param_node(child, source)
            if param is not None:
                params.append(param)

        return params

    def _parse_python_param_node(
        self, node: tree_sitter.Node, source: bytes
    ) -> ParameterInfo | None:
        """Parse a single Python parameter AST node."""
        name: str | None = None
        type_ann: str | None = None
        default: str | None = None

        if node.type == "identifier":
            name = _node_text(node, source)
        elif node.type == "typed_parameter":
            # typed_parameter: the identifier child has no field name,
            # so we find the first identifier child directly
            for child in node.children:
                if child.type == "identifier":
                    name = _node_text(child, source)
                    break
            type_child = node.child_by_field_name("type")
            if type_child:
                type_ann = _node_text(type_child, source)
        elif node.type == "default_parameter":
            name_child = node.child_by_field_name("name")
            if name_child:
                name = _node_text(name_child, source)
            value_child = node.child_by_field_name("value")
            if value_child:
                default = _node_text(value_child, source)
        elif node.type == "typed_default_parameter":
            name_child = node.child_by_field_name("name")
            if name_child:
                name = _node_text(name_child, source)
            type_child = node.child_by_field_name("type")
            if type_child:
                type_ann = _node_text(type_child, source)
            value_child = node.child_by_field_name("value")
            if value_child:
                default = _node_text(value_child, source)
        elif node.type == "list_splat_pattern":
            # *args
            for child in node.children:
                if child.type == "identifier":
                    name = _node_text(child, source)
                    break
        elif node.type == "dictionary_splat_pattern":
            # **kwargs
            for child in node.children:
                if child.type == "identifier":
                    name = _node_text(child, source)
                    break

        if name is None or name in ("self", "cls"):
            return None

        return ParameterInfo(
            name=name,
            type_annotation=type_ann,
            default_value=default,
        )

    def _extract_python_return_type(
        self, func_node: tree_sitter.Node, source: bytes
    ) -> str | None:
        """Extract return type annotation from a Python function."""
        rt_node = func_node.child_by_field_name("return_type")
        if rt_node is None:
            return None
        return _node_text(rt_node, source)

    def _extract_python_docstring(
        self, node: tree_sitter.Node, source: bytes
    ) -> str | None:
        """Extract docstring from a Python function or class definition."""
        body = node.child_by_field_name("body")
        if body is None or body.child_count == 0:
            return None

        first_stmt = body.children[0]
        if first_stmt.type != "expression_statement":
            return None

        if first_stmt.child_count == 0:
            return None

        expr = first_stmt.children[0]
        if expr.type != "string":
            return None

        text = _node_text(expr, source)
        # Strip triple quotes
        for quote in ('"""', "'''"):
            if text.startswith(quote) and text.endswith(quote):
                return text[3:-3].strip()

        return None

    def _extract_python_bases(
        self, class_node: tree_sitter.Node, source: bytes
    ) -> list[str]:
        """Extract base class names from a Python class definition."""
        bases: list[str] = []
        # The argument_list in class MyClass(Base, Mixin):
        for child in class_node.children:
            if child.type == "argument_list":
                for arg in child.children:
                    if arg.type == "identifier":
                        bases.append(_node_text(arg, source))
                    elif arg.is_named and arg.type not in ("keyword_argument",):
                        bases.append(_node_text(arg, source))
                break
        return bases

    def _process_generic_symbol(
        self,
        node: tree_sitter.Node,
        source: bytes,
        language: str,
        symbols: list[SymbolInfo],
    ) -> None:
        """Generic symbol extraction for non-Python languages."""
        name_node = node.child_by_field_name("name")
        if name_node is None:
            return
        name = _node_text(name_node, source)

        # Determine kind
        kind = self._determine_kind(node, language)

        # Build signature from the first line
        first_line = _node_text(node, source).split("\n")[0].rstrip("{").strip()

        symbols.append(
            SymbolInfo(
                name=name,
                kind=kind,  # type: ignore[arg-type]
                signature=first_line,
                docstring=None,
                start_line=node.start_point[0] + 1,
                end_line=node.end_point[0] + 1,
                parameters=[],
                return_type=None,
                calls=[],
            )
        )

    def _determine_kind(self, node: tree_sitter.Node, language: str) -> str:
        """Determine the symbol kind from the AST node type."""
        node_type = node.type
        class_types = {
            "class_definition",
            "class_declaration",
            "class_specifier",
            "struct_item",
            "struct_specifier",
            "enum_item",
            "trait_item",
            "interface_declaration",
            "class",
            "module",
            "type_declaration",
        }
        method_types = {"method_definition", "method_declaration", "method"}
        if node_type in class_types:
            return "class"
        if node_type in method_types:
            return "method"
        return "function"

    def _extract_imports(
        self,
        root: tree_sitter.Node,
        source: bytes,
        language: str,
    ) -> list[ImportInfo]:
        """Extract import statements from the AST."""
        imports: list[ImportInfo] = []

        for child in root.children:
            if language == "python":
                self._extract_python_imports(child, source, imports)
            # Other languages can be added here as needed

        return imports

    def _extract_python_imports(
        self,
        node: tree_sitter.Node,
        source: bytes,
        imports: list[ImportInfo],
    ) -> None:
        """Extract Python import statements."""
        if node.type == "import_statement":
            # import os / import os.path
            for child in node.children:
                if child.type == "dotted_name":
                    module = _node_text(child, source)
                    imports.append(ImportInfo(module=module, names=[]))
                elif child.type == "aliased_import":
                    name_node = child.child_by_field_name("name")
                    if name_node:
                        module = _node_text(name_node, source)
                        imports.append(ImportInfo(module=module, names=[]))

        elif node.type == "import_from_statement":
            # from module import name1, name2
            module_node = node.child_by_field_name("module_name")
            if module_node is None:
                # Try to find the dotted_name after 'from'
                for child in node.children:
                    if child.type == "dotted_name":
                        module_node = child
                        break
                    elif child.type == "relative_import":
                        module_node = child
                        break

            if module_node is None:
                return

            module = _node_text(module_node, source)
            names: list[str] = []

            # Collect imported names
            found_import = False
            for child in node.children:
                if child.type == "import":
                    found_import = True
                    continue
                if found_import:
                    if child.type == "dotted_name":
                        names.append(_node_text(child, source))
                    elif child.type == "aliased_import":
                        name_child = child.child_by_field_name("name")
                        if name_child:
                            names.append(_node_text(name_child, source))
                    elif child.type == "wildcard_import":
                        names.append("*")

            imports.append(ImportInfo(module=module, names=names))
