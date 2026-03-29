from __future__ import annotations

import math
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from codetex_mcp.embeddings.embedder import Embedder
from codetex_mcp.exceptions import EmbeddingError


class TestEmbedderConstants:
    def test_model_name(self) -> None:
        assert Embedder.MODEL_NAME == "all-MiniLM-L6-v2"

    def test_dimensions(self) -> None:
        assert Embedder.DIMENSIONS == 384


class TestLazyLoading:
    def test_model_not_loaded_at_construction(self) -> None:
        embedder = Embedder()
        assert embedder._model is None

    def test_model_loaded_on_first_embed(self) -> None:
        embedder = Embedder()
        mock_model = MagicMock()
        mock_model.encode.return_value = np.zeros(384)

        with patch(
            "codetex_mcp.embeddings.embedder.SentenceTransformer",
            return_value=mock_model,
        ):
            embedder.embed("test")

        assert embedder._model is mock_model

    def test_model_loaded_on_first_embed_batch(self) -> None:
        embedder = Embedder()
        mock_model = MagicMock()
        mock_model.encode.return_value = np.zeros((2, 384))

        with patch(
            "codetex_mcp.embeddings.embedder.SentenceTransformer",
            return_value=mock_model,
        ):
            embedder.embed_batch(["a", "b"])

        assert embedder._model is mock_model

    def test_model_loaded_only_once(self) -> None:
        embedder = Embedder()
        mock_model = MagicMock()
        mock_model.encode.return_value = np.zeros(384)

        with patch(
            "codetex_mcp.embeddings.embedder.SentenceTransformer",
            return_value=mock_model,
        ) as mock_cls:
            embedder.embed("first")
            embedder.embed("second")

        assert mock_cls.call_count == 1


class TestModelLoadFailure:
    def test_raises_embedding_error_on_import_failure(self) -> None:
        embedder = Embedder()
        with patch(
            "codetex_mcp.embeddings.embedder.SentenceTransformer",
            side_effect=ImportError("no module"),
        ):
            with pytest.raises(EmbeddingError, match="Failed to load embedding model"):
                embedder.embed("test")

    def test_raises_embedding_error_on_download_failure(self) -> None:
        embedder = Embedder()
        with patch(
            "codetex_mcp.embeddings.embedder.SentenceTransformer",
            side_effect=OSError("connection refused"),
        ):
            with pytest.raises(EmbeddingError, match="Failed to load embedding model"):
                embedder.embed("test")

    def test_error_message_includes_model_name(self) -> None:
        embedder = Embedder()
        with patch(
            "codetex_mcp.embeddings.embedder.SentenceTransformer",
            side_effect=RuntimeError("boom"),
        ):
            with pytest.raises(EmbeddingError, match="all-MiniLM-L6-v2"):
                embedder.embed("test")


class TestEmbed:
    def test_returns_list_of_floats(self) -> None:
        embedder = Embedder()
        mock_model = MagicMock()
        mock_model.encode.return_value = np.random.randn(384).astype(np.float32)

        with patch(
            "codetex_mcp.embeddings.embedder.SentenceTransformer",
            return_value=mock_model,
        ):
            result = embedder.embed("hello world")

        assert isinstance(result, list)
        assert len(result) == 384
        assert all(isinstance(v, float) for v in result)

    def test_returns_384_dimensions(self) -> None:
        embedder = Embedder()
        mock_model = MagicMock()
        mock_model.encode.return_value = np.ones(384, dtype=np.float32)

        with patch(
            "codetex_mcp.embeddings.embedder.SentenceTransformer",
            return_value=mock_model,
        ):
            result = embedder.embed("test text")

        assert len(result) == 384

    def test_passes_normalize_embeddings(self) -> None:
        embedder = Embedder()
        mock_model = MagicMock()
        mock_model.encode.return_value = np.zeros(384)

        with patch(
            "codetex_mcp.embeddings.embedder.SentenceTransformer",
            return_value=mock_model,
        ):
            embedder.embed("test")

        mock_model.encode.assert_called_once_with("test", normalize_embeddings=True)


class TestEmbedBatch:
    def test_returns_correct_count(self) -> None:
        embedder = Embedder()
        mock_model = MagicMock()
        mock_model.encode.return_value = np.random.randn(3, 384).astype(np.float32)

        with patch(
            "codetex_mcp.embeddings.embedder.SentenceTransformer",
            return_value=mock_model,
        ):
            results = embedder.embed_batch(["a", "b", "c"])

        assert len(results) == 3
        assert all(len(v) == 384 for v in results)

    def test_each_vector_is_list_of_floats(self) -> None:
        embedder = Embedder()
        mock_model = MagicMock()
        mock_model.encode.return_value = np.ones((2, 384), dtype=np.float32)

        with patch(
            "codetex_mcp.embeddings.embedder.SentenceTransformer",
            return_value=mock_model,
        ):
            results = embedder.embed_batch(["x", "y"])

        for vec in results:
            assert isinstance(vec, list)
            assert all(isinstance(v, float) for v in vec)

    def test_empty_input_returns_empty(self) -> None:
        embedder = Embedder()
        results = embedder.embed_batch([])
        assert results == []

    def test_empty_input_does_not_load_model(self) -> None:
        embedder = Embedder()
        embedder.embed_batch([])
        assert embedder._model is None

    def test_passes_normalize_embeddings(self) -> None:
        embedder = Embedder()
        mock_model = MagicMock()
        mock_model.encode.return_value = np.zeros((1, 384))

        with patch(
            "codetex_mcp.embeddings.embedder.SentenceTransformer",
            return_value=mock_model,
        ):
            embedder.embed_batch(["test"])

        mock_model.encode.assert_called_once_with(
            ["test"], normalize_embeddings=True
        )


class TestNormalization:
    def test_embed_returns_normalized_vector(self) -> None:
        """Verify that with normalize_embeddings=True the result is unit-length."""
        embedder = Embedder()
        # Create a normalized vector to simulate what sentence-transformers returns
        raw = np.random.randn(384).astype(np.float32)
        normalized = raw / np.linalg.norm(raw)
        mock_model = MagicMock()
        mock_model.encode.return_value = normalized

        with patch(
            "codetex_mcp.embeddings.embedder.SentenceTransformer",
            return_value=mock_model,
        ):
            result = embedder.embed("test")

        magnitude = math.sqrt(sum(v * v for v in result))
        assert abs(magnitude - 1.0) < 1e-5

    def test_embed_batch_returns_normalized_vectors(self) -> None:
        embedder = Embedder()
        raw = np.random.randn(2, 384).astype(np.float32)
        norms = np.linalg.norm(raw, axis=1, keepdims=True)
        normalized = raw / norms
        mock_model = MagicMock()
        mock_model.encode.return_value = normalized

        with patch(
            "codetex_mcp.embeddings.embedder.SentenceTransformer",
            return_value=mock_model,
        ):
            results = embedder.embed_batch(["a", "b"])

        for vec in results:
            magnitude = math.sqrt(sum(v * v for v in vec))
            assert abs(magnitude - 1.0) < 1e-5
