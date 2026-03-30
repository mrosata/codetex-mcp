from __future__ import annotations


from codetex_mcp.analysis.models import ParameterInfo, SymbolInfo
from codetex_mcp.llm.prompts import tier1_prompt, tier2_prompt, tier3_prompt


class TestTier1Prompt:
    def test_produces_nonempty_string(self) -> None:
        result = tier1_prompt(
            repo_name="my-repo",
            directory_tree="src/\n  main.py",
            file_summaries=["main.py: entry point"],
            technologies=["Python", "FastAPI"],
        )
        assert isinstance(result, str)
        assert len(result) > 0

    def test_contains_repo_name(self) -> None:
        result = tier1_prompt(
            repo_name="codetex-mcp",
            directory_tree="src/",
            file_summaries=[],
            technologies=[],
        )
        assert "codetex-mcp" in result

    def test_contains_technologies(self) -> None:
        result = tier1_prompt(
            repo_name="repo",
            directory_tree="",
            file_summaries=[],
            technologies=["Python", "SQLite"],
        )
        assert "Python" in result
        assert "SQLite" in result

    def test_contains_directory_tree(self) -> None:
        tree = "src/\n  app.py\n  utils.py"
        result = tier1_prompt(
            repo_name="repo",
            directory_tree=tree,
            file_summaries=[],
            technologies=[],
        )
        assert "src/" in result
        assert "app.py" in result

    def test_contains_file_summaries(self) -> None:
        result = tier1_prompt(
            repo_name="repo",
            directory_tree="",
            file_summaries=["app.py: main application", "utils.py: helper functions"],
            technologies=[],
        )
        assert "main application" in result
        assert "helper functions" in result

    def test_empty_technologies_shows_unknown(self) -> None:
        result = tier1_prompt(
            repo_name="repo",
            directory_tree="",
            file_summaries=[],
            technologies=[],
        )
        assert "unknown" in result

    def test_empty_summaries_shows_placeholder(self) -> None:
        result = tier1_prompt(
            repo_name="repo",
            directory_tree="",
            file_summaries=[],
            technologies=[],
        )
        assert "no file summaries" in result


class TestTier2Prompt:
    def test_produces_nonempty_string(self) -> None:
        result = tier2_prompt(
            file_path="src/main.py",
            content="def main(): pass",
            symbols=[],
        )
        assert isinstance(result, str)
        assert len(result) > 0

    def test_contains_file_path(self) -> None:
        result = tier2_prompt(
            file_path="src/utils.py",
            content="",
            symbols=[],
        )
        assert "src/utils.py" in result

    def test_contains_source_content(self) -> None:
        content = "def hello():\n    print('world')"
        result = tier2_prompt(
            file_path="test.py",
            content=content,
            symbols=[],
        )
        assert "hello()" in result
        assert "print('world')" in result

    def test_contains_symbol_info(self) -> None:
        symbols = [
            SymbolInfo(
                name="process",
                kind="function",
                signature="def process(data: list) -> bool",
                start_line=1,
                end_line=10,
                parameters=[
                    ParameterInfo(name="data", type_annotation="list"),
                ],
                return_type="bool",
            ),
        ]
        result = tier2_prompt(
            file_path="test.py",
            content="",
            symbols=symbols,
        )
        assert "process" in result
        assert "function" in result
        assert "data" in result

    def test_empty_symbols_shows_placeholder(self) -> None:
        result = tier2_prompt(
            file_path="test.py",
            content="",
            symbols=[],
        )
        assert "no symbols extracted" in result

    def test_asks_for_role_classification(self) -> None:
        result = tier2_prompt(
            file_path="test.py",
            content="",
            symbols=[],
        )
        assert "Role" in result

    def test_symbol_with_default_value(self) -> None:
        symbols = [
            SymbolInfo(
                name="fetch",
                kind="function",
                signature="def fetch(url: str, timeout: int = 30)",
                start_line=1,
                end_line=5,
                parameters=[
                    ParameterInfo(name="url", type_annotation="str"),
                    ParameterInfo(
                        name="timeout", type_annotation="int", default_value="30"
                    ),
                ],
            ),
        ]
        result = tier2_prompt(
            file_path="test.py",
            content="",
            symbols=symbols,
        )
        assert "timeout" in result
        assert "30" in result


class TestTier3Prompt:
    def test_produces_nonempty_string(self) -> None:
        symbol = SymbolInfo(
            name="parse",
            kind="function",
            signature="def parse(text: str) -> dict",
        )
        result = tier3_prompt(symbol=symbol, file_context="")
        assert isinstance(result, str)
        assert len(result) > 0

    def test_contains_symbol_name(self) -> None:
        symbol = SymbolInfo(
            name="calculate",
            kind="method",
            signature="def calculate(self, x: int) -> float",
        )
        result = tier3_prompt(symbol=symbol, file_context="")
        assert "calculate" in result

    def test_contains_parameters(self) -> None:
        symbol = SymbolInfo(
            name="process",
            kind="function",
            signature="def process(data: list, verbose: bool = False)",
            parameters=[
                ParameterInfo(name="data", type_annotation="list"),
                ParameterInfo(
                    name="verbose", type_annotation="bool", default_value="False"
                ),
            ],
        )
        result = tier3_prompt(symbol=symbol, file_context="")
        assert "data" in result
        assert "list" in result
        assert "verbose" in result
        assert "False" in result

    def test_contains_return_type(self) -> None:
        symbol = SymbolInfo(
            name="get_value",
            kind="function",
            signature="def get_value() -> int",
            return_type="int",
        )
        result = tier3_prompt(symbol=symbol, file_context="")
        assert "int" in result

    def test_contains_calls(self) -> None:
        symbol = SymbolInfo(
            name="run",
            kind="function",
            signature="def run()",
            calls=["setup", "execute", "cleanup"],
        )
        result = tier3_prompt(symbol=symbol, file_context="")
        assert "setup" in result
        assert "execute" in result
        assert "cleanup" in result

    def test_contains_docstring(self) -> None:
        symbol = SymbolInfo(
            name="init",
            kind="function",
            signature="def init()",
            docstring="Initialize the system with default configuration.",
        )
        result = tier3_prompt(symbol=symbol, file_context="")
        assert "Initialize the system" in result

    def test_contains_file_context(self) -> None:
        symbol = SymbolInfo(
            name="helper",
            kind="function",
            signature="def helper()",
        )
        result = tier3_prompt(
            symbol=symbol,
            file_context="import os\n\ndef helper():\n    return os.getcwd()",
        )
        assert "os.getcwd()" in result

    def test_no_parameters_shows_placeholder(self) -> None:
        symbol = SymbolInfo(
            name="noop",
            kind="function",
            signature="def noop()",
        )
        result = tier3_prompt(symbol=symbol, file_context="")
        assert "no parameters" in result

    def test_no_return_type_shows_placeholder(self) -> None:
        symbol = SymbolInfo(
            name="noop",
            kind="function",
            signature="def noop()",
        )
        result = tier3_prompt(symbol=symbol, file_context="")
        assert "not specified" in result

    def test_no_calls_shows_placeholder(self) -> None:
        symbol = SymbolInfo(
            name="noop",
            kind="function",
            signature="def noop()",
        )
        result = tier3_prompt(symbol=symbol, file_context="")
        assert "none detected" in result

    def test_no_docstring_shows_placeholder(self) -> None:
        symbol = SymbolInfo(
            name="noop",
            kind="function",
            signature="def noop()",
        )
        result = tier3_prompt(symbol=symbol, file_context="")
        assert "no docstring" in result

    def test_class_kind_in_instructions(self) -> None:
        symbol = SymbolInfo(
            name="MyClass",
            kind="class",
            signature="class MyClass(Base)",
        )
        result = tier3_prompt(symbol=symbol, file_context="")
        assert "class" in result
        assert "Class" in result
