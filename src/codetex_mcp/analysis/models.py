"""Data models for static analysis results."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


@dataclass
class ParameterInfo:
    """Parameter definition with optional type annotation and default value."""

    name: str
    type_annotation: str | None = None
    default_value: str | None = None


@dataclass
class SymbolInfo:
    """Represents a function, method, class, variable, or constant."""

    name: str
    kind: Literal["function", "method", "class", "variable", "constant"]
    signature: str
    docstring: str | None = None
    start_line: int = 0
    end_line: int = 0
    parameters: list[ParameterInfo] = field(default_factory=list)
    return_type: str | None = None
    calls: list[str] = field(default_factory=list)


@dataclass
class ImportInfo:
    """Represents an import statement with module and imported names."""

    module: str
    names: list[str] = field(default_factory=list)


@dataclass
class FileAnalysis:
    """Result of parsing a single source file."""

    path: str
    language: str | None
    imports: list[ImportInfo] = field(default_factory=list)
    symbols: list[SymbolInfo] = field(default_factory=list)
    lines_of_code: int = 0
    token_count: int = 0
