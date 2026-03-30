"""Prompt templates for the three-tier summarization pipeline."""

from __future__ import annotations

from codetex_mcp.analysis.models import SymbolInfo


def tier1_prompt(
    repo_name: str,
    directory_tree: str,
    file_summaries: list[str],
    technologies: list[str],
) -> str:
    """Build the Tier 1 (repository overview) prompt."""
    tech_list = ", ".join(technologies) if technologies else "unknown"
    summaries_block = (
        "\n\n".join(file_summaries)
        if file_summaries
        else "(no file summaries available)"
    )

    return f"""\
Analyze the following repository and produce a structured overview.

## Repository: {repo_name}

### Technologies
{tech_list}

### Directory Structure
```
{directory_tree}
```

### File Summaries
{summaries_block}

## Instructions

Produce a repository overview in the following markdown format:

### Purpose
One paragraph describing what this repository does and its primary use case.

### Architecture
Describe the high-level architecture: key modules, how they interact, data flow.

### Key Components
Bullet list of the most important files/modules with a one-line description each.

### Technologies
Bullet list of languages, frameworks, and major libraries used.

### Entry Points
Where does execution start? List CLI commands, server endpoints, or main functions."""


def tier2_prompt(
    file_path: str,
    content: str,
    symbols: list[SymbolInfo],
) -> str:
    """Build the Tier 2 (file summary) prompt."""
    symbols_block = ""
    if symbols:
        lines = []
        for s in symbols:
            params = ""
            if s.parameters:
                param_strs = []
                for p in s.parameters:
                    part = p.name
                    if p.type_annotation:
                        part += f": {p.type_annotation}"
                    if p.default_value:
                        part += f" = {p.default_value}"
                    param_strs.append(part)
                params = ", ".join(param_strs)
            ret = f" -> {s.return_type}" if s.return_type else ""
            lines.append(
                f"- {s.kind} `{s.name}({params}){ret}` (lines {s.start_line}-{s.end_line})"
            )
        symbols_block = "\n".join(lines)
    else:
        symbols_block = "(no symbols extracted)"

    return f"""\
Analyze the following source file and produce a structured summary.

## File: `{file_path}`

### Source Code
```
{content}
```

### Extracted Symbols
{symbols_block}

## Instructions

Produce a file summary in the following markdown format:

### Purpose
One paragraph describing what this file does and why it exists.

### Public Interface
Bullet list of the key functions/classes/exports that other modules use.

### Dependencies
Bullet list of notable imports and what they're used for.

### Role
Classify this file as one of: entry_point, core_logic, utility, model, configuration, test, documentation."""


def tier3_prompt(
    symbol: SymbolInfo,
    file_context: str,
) -> str:
    """Build the Tier 3 (symbol detail) prompt."""
    params_block = ""
    if symbol.parameters:
        lines = []
        for p in symbol.parameters:
            type_str = f": {p.type_annotation}" if p.type_annotation else ""
            default_str = f" (default: {p.default_value})" if p.default_value else ""
            lines.append(f"- `{p.name}{type_str}`{default_str}")
        params_block = "\n".join(lines)
    else:
        params_block = "(no parameters)"

    ret_block = f"`{symbol.return_type}`" if symbol.return_type else "(not specified)"

    calls_block = ""
    if symbol.calls:
        calls_block = ", ".join(f"`{c}`" for c in symbol.calls)
    else:
        calls_block = "(none detected)"

    docstring_block = symbol.docstring if symbol.docstring else "(no docstring)"

    return f"""\
Analyze the following {symbol.kind} and produce a detailed summary.

## {symbol.kind.title()}: `{symbol.signature}`

### Docstring
{docstring_block}

### Parameters
{params_block}

### Return Type
{ret_block}

### Calls
{calls_block}

### File Context
```
{file_context}
```

## Instructions

Produce a symbol summary in the following markdown format:

### Description
One paragraph describing what this {symbol.kind} does, its purpose, and when to use it.

### Parameters
For each parameter: name, type, and what it controls.

### Returns
What the return value represents and its type.

### Relationships
What other functions/classes does this call or depend on, and what calls it."""
