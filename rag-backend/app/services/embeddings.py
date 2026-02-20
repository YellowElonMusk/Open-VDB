"""Embeddings service using sentence transformers"""

from typing import List
from sentence_transformers import SentenceTransformer
import torch
import structlog
from app.config import settings

logger = structlog.get_logger(__name__)


class EmbeddingsService:
    """Service for generating embeddings from text"""

    def __init__(self):
        self.model: SentenceTransformer | None = None
        self.device = "cuda" if torch.cuda.is_available() else "cpu"

    async def load_model(self):
        """Load the sentence transformer model"""
        try:
            logger.info(
                "Loading embeddings model",
                model=settings.embeddings_model,
                device=self.device
            )

            self.model = SentenceTransformer(settings.embeddings_model, device=self.device)

            logger.info(
                "Embeddings model loaded",
                dimension=self.model.get_sentence_embedding_dimension()
            )

        except Exception as e:
            logger.error("Failed to load embeddings model", error=str(e))
            raise

    def encode_text(self, text: str) -> List[float]:
        """
        Generate embedding for a single text

        Args:
            text: Input text

        Returns:
            Embedding vector
        """
        if self.model is None:
            raise RuntimeError("Embeddings model not loaded")

        try:
            embedding = self.model.encode(
                text,
                convert_to_numpy=True,
                normalize_embeddings=True
            )
            return embedding.tolist()

        except Exception as e:
            logger.error("Failed to encode text", error=str(e))
            raise

    def encode_batch(self, texts: List[str], batch_size: int = 32) -> List[List[float]]:
        """
        Generate embeddings for multiple texts

        Args:
            texts: List of input texts
            batch_size: Batch size for processing

        Returns:
            List of embedding vectors
        """
        if self.model is None:
            raise RuntimeError("Embeddings model not loaded")

        try:
            embeddings = self.model.encode(
                texts,
                batch_size=batch_size,
                convert_to_numpy=True,
                normalize_embeddings=True,
                show_progress_bar=len(texts) > 100
            )
            return embeddings.tolist()

        except Exception as e:
            logger.error("Failed to encode batch", error=str(e), count=len(texts))
            raise

    @property
    def dimension(self) -> int:
        """Get embedding dimension"""
        if self.model is None:
            return settings.embeddings_dimension
        return self.model.get_sentence_embedding_dimension()


# Global instance
embeddings_service = EmbeddingsService()
