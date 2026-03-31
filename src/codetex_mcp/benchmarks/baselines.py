"""Naive baseline implementations for benchmark comparison.

Provides grep-based search and raw file dump as baseline context strategies.
"""

from __future__ import annotations

import subprocess
from pathlib import Path


def grep_search(repo_path: Path, query: str, max_results: int = 20) -> list[str]:
    """Keyword-based file search using grep.

    Splits the query into keywords and searches for files containing
    any keyword. Returns unique file paths sorted by match count (descending).
    """
    keywords = query.lower().split()
    if not keywords:
        return []

    file_hits: dict[str, int] = {}
    for keyword in keywords:
        try:
            result = subprocess.run(
                ["grep", "-rl", "--include=*.py", "-i", keyword, str(repo_path)],
                capture_output=True,
                text=True,
                timeout=30,
            )
            for line in result.stdout.strip().splitlines():
                if line:
                    # Convert to relative path
                    try:
                        rel = str(Path(line).relative_to(repo_path))
                    except ValueError:
                        rel = line
                    file_hits[rel] = file_hits.get(rel, 0) + 1
        except (subprocess.TimeoutExpired, FileNotFoundError):
            continue

    # Sort by hit count descending, take top N
    sorted_files = sorted(file_hits.keys(), key=lambda f: file_hits[f], reverse=True)
    return sorted_files[:max_results]


def raw_file_context(repo_path: Path, file_paths: list[str]) -> str:
    """Concatenate raw file contents as naive context.

    Returns the full content of each file, separated by file path headers.
    """
    parts: list[str] = []
    for file_path in file_paths:
        full_path = repo_path / file_path
        if full_path.is_file():
            try:
                content = full_path.read_text(errors="replace")
                parts.append(f"# {file_path}\n\n{content}")
            except OSError:
                continue
    return "\n\n---\n\n".join(parts)


def grep_context(repo_path: Path, query: str, context_lines: int = 5) -> str:
    """Grep with surrounding context lines as naive context.

    Splits query into keywords and returns grep output with context.
    """
    keywords = query.lower().split()
    if not keywords:
        return ""

    parts: list[str] = []
    for keyword in keywords:
        try:
            result = subprocess.run(
                [
                    "grep",
                    "-rn",
                    "--include=*.py",
                    "-i",
                    f"-C{context_lines}",
                    keyword,
                    str(repo_path),
                ],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.stdout.strip():
                parts.append(f"# grep: {keyword}\n\n{result.stdout.strip()}")
        except (subprocess.TimeoutExpired, FileNotFoundError):
            continue

    return "\n\n---\n\n".join(parts)
