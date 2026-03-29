class CodetexError(Exception):
    """Base exception. All codetex errors inherit from this."""


class RepositoryNotFoundError(CodetexError):
    """Repo name doesn't match any registered repository."""


class RepositoryAlreadyExistsError(CodetexError):
    """Attempting to add a repo that's already registered."""


class GitError(CodetexError):
    """Wraps git subprocess failures with actionable context."""


class GitAuthError(GitError):
    """Authentication failed — includes setup guidance."""

    def __init__(self, url: str) -> None:
        super().__init__(
            f"Authentication failed for '{url}'. "
            "Ensure SSH keys are configured (git@...) or a credential helper "
            "is set up for HTTPS. See: https://git-scm.com/doc/credential-helpers"
        )


class IndexError(CodetexError):  # noqa: A001
    """Error during indexing pipeline."""


class LLMError(CodetexError):
    """LLM API call failed."""


class RateLimitError(LLMError):
    """Rate limit hit — handled by automatic retry with backoff."""


class ConfigError(CodetexError):
    """Invalid configuration value."""


class DatabaseError(CodetexError):
    """Database corruption or migration failure."""


class EmbeddingError(CodetexError):
    """Embedding model load or inference failure."""


class NoIndexError(CodetexError):
    """Repo exists but has no index — user needs to run `codetex index` first."""
