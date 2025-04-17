import os
import logging
from typing import List, Optional
from openai import OpenAI, OpenAIError

logger = logging.getLogger(__name__)

# Read embedding model from environment or use default
OPENAI_EMBEDDING_MODEL = os.getenv("OPENAI_EMBEDDING_MODEL", "text-embedding-ada-002")

def get_openai_embeddings(
    openai_client: Optional[OpenAI],
    texts: List[str]
) -> Optional[List[List[float]]]:
    """
    Generates embeddings for a list of texts using a provided OpenAI client.

    Args:
        openai_client: An initialized OpenAI client instance.
        texts: A list of text strings to embed.

    Returns:
        A list of embedding vectors (each a list of floats), or None if an error occurs.
    """
    if not openai_client:
        logger.error("OpenAI client not provided or initialized. Cannot generate embeddings.")
        return None
    if not texts:
        logger.warning("Received empty list of texts for embedding.")
        return []

    try:
        logger.debug(f"Generating embeddings for {len(texts)} texts using '{OPENAI_EMBEDDING_MODEL}'...")
        # Replace newlines for safety, as recommended by OpenAI embedding docs
        safe_texts = [text.replace("\n", " ") for text in texts]
        response = openai_client.embeddings.create(
            input=safe_texts,
            model=OPENAI_EMBEDDING_MODEL
        )
        embeddings = [item.embedding for item in response.data]
        logger.debug(f"Successfully generated {len(embeddings)} embeddings.")
        return embeddings
    except OpenAIError as e:
        logger.error(f"OpenAI API error during embedding: {e}", exc_info=True)
        return None
    except Exception as e:
        logger.error(f"Unexpected error during embedding generation: {e}", exc_info=True)
        return None
