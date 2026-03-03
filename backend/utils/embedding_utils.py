import os
import logging
from typing import List, Optional
from mistralai import Mistral

logger = logging.getLogger(__name__)

MISTRAL_EMBEDDING_MODEL = os.getenv("MISTRAL_EMBEDDING_MODEL", "mistral-embed")

def get_mistral_embeddings(
    mistral_client: Optional[Mistral],
    texts: List[str]
) -> Optional[List[List[float]]]:
    """
    Generates embeddings for a list of texts using a provided Mistral client.

    Args:
        mistral_client: An initialized Mistral client instance.
        texts: A list of text strings to embed.

    Returns:
        A list of embedding vectors (each a list of floats), or None if an error occurs.
    """
    if not mistral_client:
        logger.error("Mistral client not provided or initialized. Cannot generate embeddings.")
        return None
    if not texts:
        logger.warning("Received empty list of texts for embedding.")
        return []

    try:
        logger.debug(f"Generating embeddings for {len(texts)} texts using '{MISTRAL_EMBEDDING_MODEL}'...")
        safe_texts = [text.replace("\n", " ") for text in texts]
        response = mistral_client.embeddings.create(
            model=MISTRAL_EMBEDDING_MODEL,
            inputs=safe_texts
        )
        embeddings = [item.embedding for item in response.data]
        logger.debug(f"Successfully generated {len(embeddings)} embeddings.")
        return embeddings
    except Exception as e:
        logger.error(f"Mistral API error during embedding: {e}", exc_info=True)
        return None
