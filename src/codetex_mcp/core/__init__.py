"""Application wiring — AppContext dataclass and create_app factory."""

from __future__ import annotations

from dataclasses import dataclass

from codetex_mcp.analysis.fallback_parser import FallbackParser
from codetex_mcp.analysis.parser import Parser
from codetex_mcp.analysis.tree_sitter import TreeSitterParser
from codetex_mcp.config.settings import Settings
from codetex_mcp.core.context_store import ContextStore
from codetex_mcp.core.indexer import Indexer
from codetex_mcp.core.repo_manager import RepoManager
from codetex_mcp.core.search_engine import SearchEngine
from codetex_mcp.core.syncer import Syncer
from codetex_mcp.embeddings.embedder import Embedder
from codetex_mcp.git.operations import GitOperations
from codetex_mcp.llm.provider import AnthropicProvider, LLMProvider
from codetex_mcp.llm.rate_limiter import RateLimiter
from codetex_mcp.storage.database import Database


@dataclass
class AppContext:
    settings: Settings
    db: Database
    git: GitOperations
    parser: Parser
    llm: LLMProvider
    embedder: Embedder
    repo_manager: RepoManager
    indexer: Indexer
    syncer: Syncer
    context_store: ContextStore
    search_engine: SearchEngine


async def create_app(settings: Settings | None = None) -> AppContext:
    """Wire the full application object graph."""
    settings = settings or Settings.load()

    assert settings.db_path is not None  # Always set after __post_init__ / load()
    db = Database(settings.db_path)
    await db.connect()
    await db.migrate()

    git = GitOperations(settings)

    tree_sitter = TreeSitterParser()
    fallback = FallbackParser()
    parser = Parser(tree_sitter, fallback)

    rate_limiter = RateLimiter(max_concurrent=settings.max_concurrent_llm_calls)
    llm = AnthropicProvider(
        api_key=settings.llm_api_key or "",
        model=settings.llm_model,
        rate_limiter=rate_limiter,
    )
    embedder = Embedder()

    repo_manager = RepoManager(db, git, settings)
    context_store = ContextStore(db)
    search_engine = SearchEngine(db, embedder)
    indexer = Indexer(db, git, parser, llm, embedder, settings)
    syncer = Syncer(db, git, parser, llm, embedder, settings)

    return AppContext(
        settings=settings,
        db=db,
        git=git,
        parser=parser,
        llm=llm,
        embedder=embedder,
        repo_manager=repo_manager,
        indexer=indexer,
        syncer=syncer,
        context_store=context_store,
        search_engine=search_engine,
    )
