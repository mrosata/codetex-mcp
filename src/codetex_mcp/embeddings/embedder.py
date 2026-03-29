from __future__ import annotations

from sentence_transformers import SentenceTransformer

from codetex_mcp.exceptions import EmbeddingError


class Embedder:
    """Wraps sentence-transformers for local embedding generation with lazy model loading."""

    MODEL_NAME = "all-MiniLM-L6-v2"
    DIMENSIONS = 384

    def __init__(self) -> None:
        self._model: SentenceTransformer | None = None

    def _load_model(self) -> None:
        """Load the sentence-transformers model on first use."""
        if self._model is not None:
            return
        try:
            self._model = SentenceTransformer(self.MODEL_NAME)
        except Exception as exc:
            raise EmbeddingError(
                f"Failed to load embedding model '{self.MODEL_NAME}': {exc}. "
                "The model (~23MB) is downloaded on first use. "
                "Check your internet connection and disk space."
            ) from exc

    def embed(self, text: str) -> list[float]:
        """Embed a single text string into a 384-dimension vector."""
        self._load_model()
        # SentenceTransformer.encode returns numpy array
        vector = self._model.encode(text, normalize_embeddings=True)  # type: ignore[union-attr]
        return vector.tolist()  # type: ignore[union-attr]

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Embed multiple texts into 384-dimension vectors."""
        if not texts:
            return []
        self._load_model()
        vectors = self._model.encode(texts, normalize_embeddings=True)  # type: ignore[union-attr]
        return [v.tolist() for v in vectors]  # type: ignore[union-attr]
