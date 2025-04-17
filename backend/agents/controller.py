from agno.agent import Agent
from agno.models.openai import OpenAIChat # Example model
from agno.models.anthropic import Claude   # Example model
import json
import os
import logging
from typing import Any, List, Optional, Dict
import chromadb # Import ChromaDB type hint
from openai import OpenAI, OpenAIError # Import OpenAI for embeddings
# --- Import shared utility ---
from utils.embedding_utils import get_openai_embeddings
# --- End Import ---

# Set up logger
logger = logging.getLogger(__name__)

# --- Configuration ---
# Read model ID from environment variable or use default
DEFAULT_CONTROLLER_MODEL = "gpt-4.1-mini" # Adjust as needed
CONTROLLER_MODEL_ID = os.getenv("CONTROLLER_LLM_MODEL", DEFAULT_CONTROLLER_MODEL)
# OpenAI Configuration for embeddings (should match extractor)
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_EMBEDDING_MODEL = "text-embedding-ada-002"
# Number of relevant chunks to retrieve from vector store
DEFAULT_RELEVANT_CHUNKS = 3
N_RELEVANT_CHUNKS = int(os.getenv("CONTROLLER_RELEVANT_CHUNKS", DEFAULT_RELEVANT_CHUNKS))


class ControllerAgent:
    """
    Agent 4: Applies the selected control prompts to the *most relevant*
             text chunks retrieved from a vector store.
    """
    def __init__(self):
        logger.info(f"Initializing ControllerAgent with LLM model: {CONTROLLER_MODEL_ID}")
        # LLM Agent for control execution
        self.llm_agent = Agent(
             model=OpenAIChat(id=CONTROLLER_MODEL_ID),
             instructions=[
                 "You are a control verification assistant.",
                 "Execute the specific instruction provided for the control precisely based on the provided text chunk.",
                 "Respond ONLY with the requested output format or findings."
             ],
             markdown=False,
             debug_mode=os.getenv('AGNO_DEBUG_MODE', 'false').lower() == 'true'
         )
        # OpenAI Client for embedding control queries
        try:
            self.openai_client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None
            if not self.openai_client:
                 logger.error("Failed to initialize OpenAI client for embeddings (missing API key).")
        except Exception as e:
            logger.error(f"Failed to initialize OpenAI client for embeddings: {e}", exc_info=True)
            self.openai_client = None

        logger.info("ControllerAgent initialized.")

    # --- Modified run method ---
    def run(self, vector_collection: chromadb.Collection, prompt_files: list[str]) -> list[dict[str, Any]]:
        """
        Applies each control prompt to the N most relevant chunks found in the vector store.
        Returns a flattened list of dictionaries, one per relevant chunk processed for each control,
        containing: {'id', 'description', 'instructions', 'result', 'chunk_id', 'distance'}
        """
        if not vector_collection:
             logger.error("Received an invalid or empty vector collection.")
             # Return specific error marker?
             return [{'id': 'CONTROLLER_ERROR', 'result': 'Invalid vector collection received', 'chunk_id': 'N/A'}]
        if not self.openai_client:
             logger.error("OpenAI client for embeddings not available in ControllerAgent.")
             return [{'id': 'CONTROLLER_ERROR', 'result': 'OpenAI client not configured for embeddings', 'chunk_id': 'N/A'}]

        logger.info(f"Applying {len(prompt_files)} controls using vector collection '{vector_collection.name}'. Will query top {N_RELEVANT_CHUNKS} chunks.")
        detailed_results = []

        for prompt_file in prompt_files:
            control_id = os.path.basename(prompt_file).replace('.json', '')
            description = "N/A"
            instructions = []
            control_load_error = None

            # --- Load Control Details ---
            try:
                logger.debug(f"Loading prompt file: {prompt_file}")
                with open(prompt_file, 'r', encoding='utf-8') as f:
                    control_data = json.load(f)
                control_id = control_data.get("control_id", control_id)
                instructions = control_data.get("prompt_instructions", [])
                description = control_data.get("description", "N/A")
                if not instructions:
                    logger.warning(f"No 'prompt_instructions' found in {prompt_file}. Skipping control.")
                    control_load_error = "Error: Prompt instructions missing."
            except FileNotFoundError:
                logger.error(f"Prompt file not found: {prompt_file}")
                control_load_error = "Error: Prompt file missing."
            except json.JSONDecodeError as e:
                logger.error(f"Invalid JSON in prompt file: {prompt_file}: {e}")
                control_load_error = "Error: Invalid JSON format."
            except Exception as e:
                logger.error(f"Unexpected error loading {prompt_file}: {e}", exc_info=True)
                control_load_error = f"Error: Unexpected loading prompt ({e})"

            if control_load_error:
                 detailed_results.append({
                     'id': control_id,
                     'description': description,
                     'instructions': instructions,
                     'result': control_load_error,
                     'chunk_id': 'PROMPT_LOAD_ERROR', # Use a specific marker
                     'distance': -1.0
                 })
                 continue # Move to the next prompt file

            # --- Generate Query Embedding for the Control ---
            query_text = f"Control Description: {description}\nInstructions:\n" + "\n".join(f"- {inst}" for inst in instructions)
            # Use the shared utility function, passing the client instance
            query_embedding = get_openai_embeddings(self.openai_client, [query_text])

            if not query_embedding:
                 logger.error(f"Failed to generate query embedding for control '{control_id}'. Skipping.")
                 detailed_results.append({
                     'id': control_id,
                     'description': description,
                     'instructions': instructions,
                     'result': "Error: Failed to create query embedding for control.",
                     'chunk_id': 'EMBEDDING_ERROR',
                     'distance': -1.0
                 })
                 continue

            # --- Query Vector Store for Relevant Chunks ---
            try:
                 logger.info(f"Querying collection '{vector_collection.name}' for control '{control_id}'...")
                 query_results = vector_collection.query(
                     query_embeddings=query_embedding, # Pass the single embedding in a list
                     n_results=N_RELEVANT_CHUNKS,
                     include=['documents', 'distances'] # Request documents and distances
                 )
                 logger.info(f"Found {len(query_results.get('ids', [[]])[0]) if query_results else 0} potentially relevant chunks for '{control_id}'.")

            except Exception as e:
                 logger.error(f"Error querying ChromaDB for control '{control_id}': {e}", exc_info=True)
                 detailed_results.append({
                     'id': control_id,
                     'description': description,
                     'instructions': instructions,
                     'result': f"Error: Vector store query failed ({e})",
                     'chunk_id': 'QUERY_ERROR',
                     'distance': -1.0
                 })
                 continue # Move to next control

            # --- Process Relevant Chunks ---
            # Check if query_results and its inner lists are valid
            retrieved_ids = query_results.get('ids', [[]])[0]
            retrieved_documents = query_results.get('documents', [[]])[0]
            retrieved_distances = query_results.get('distances', [[]])[0]

            if not retrieved_ids:
                 logger.warning(f"No relevant chunks found in vector store for control '{control_id}'.")
                 # Optionally add a result indicating no chunks found
                 detailed_results.append({
                     'id': control_id,
                     'description': description,
                     'instructions': instructions,
                     'result': "Info: No relevant text chunks found via vector search.",
                     'chunk_id': 'NO_RELEVANT_CHUNKS',
                     'distance': -1.0
                 })
                 continue # Move to next control

            # Loop through the *retrieved relevant* chunks
            for i, chunk_id in enumerate(retrieved_ids):
                 chunk_text = retrieved_documents[i]
                 chunk_distance = retrieved_distances[i]
                 logger.info(f"Applying control '{control_id}' to relevant chunk {i+1}/{len(retrieved_ids)} (ID: {chunk_id}, Distance: {chunk_distance:.4f})...")
                 result_content_for_chunk = "Error: Processing failed before LLM call."

                 try:
                    # Construct the prompt for the LLM using the current chunk
                    full_prompt = (
                        f"Control Description: {description}\n"
                        f"Instructions:\n" + "\n".join(f"- {inst}" for inst in instructions) +
                        f"\n\n--- Relevant Document Text Chunk (ID: {chunk_id}, Distance: {chunk_distance:.4f}) Start ---\n"
                        f"{chunk_text}"
                        f"\n--- Relevant Document Text Chunk End ---"
                    )
                    # --- Uncommented for debugging --- #
                    logger.debug(f"Running LLM for control '{control_id}' chunk ID '{chunk_id}'. Prompt length: {len(full_prompt)}")
                    logger.debug("--- PROMPT START ---")
                    logger.debug(full_prompt) # Log prompt separately
                    logger.debug("--- PROMPT END ---")
                    # --------------------------------- #

                    # --- LLM Call ---
                    response = self.llm_agent.run(full_prompt, stream=False)

                    # --- Extract content ---
                    if hasattr(response, 'content') and response.content is not None:
                        result_content_for_chunk = str(response.content)
                    elif response: # Response object exists but no content
                        result_content_for_chunk = "Error: Empty Response from LLM agent."
                        logger.warning(f"LLM response for '{control_id}' chunk ID '{chunk_id}' has no content.")
                    else: # No response object
                        result_content_for_chunk = "Error: No response object from LLM agent."
                        logger.error(f"No response object from LLM agent for '{control_id}' chunk ID '{chunk_id}'.")

                    log_snippet = result_content_for_chunk[:100].replace('\n', ' ') + ("..." if len(result_content_for_chunk) > 100 else "")
                    logger.info(f"Result for '{control_id}' chunk ID '{chunk_id}' received (snippet): {log_snippet}")

                 except Exception as llm_error:
                    logger.error(f"Error applying control '{control_id}' chunk ID '{chunk_id}' via LLM: {llm_error}", exc_info=True)
                    result_content_for_chunk = f"Error: LLM execution failed ({llm_error})"

                 # Append result for this specific relevant chunk
                 detailed_results.append({
                     'id': control_id,
                     'description': description,
                     'instructions': instructions,
                     'result': result_content_for_chunk,
                     'chunk_id': chunk_id, # Store the actual chunk ID from ChromaDB
                     'distance': chunk_distance # Store the distance metric
                 })
            # --- End of relevant chunk loop ---
        # --- End of prompt loop ---

        logger.info(f"Finished applying controls to relevant chunks. Total results generated: {len(detailed_results)}")
        return detailed_results
