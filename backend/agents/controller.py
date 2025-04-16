from agno.agent import Agent
from agno.models.openai import OpenAIChat # Example model
from agno.models.anthropic import Claude   # Example model
import json
import os
import logging
from typing import Any, List

# Set up logger
logger = logging.getLogger(__name__)

# --- Configuration ---
# Read model ID from environment variable or use default
DEFAULT_CONTROLLER_MODEL = "gpt-4.1-mini"
CONTROLLER_MODEL_ID = os.getenv("CONTROLLER_LLM_MODEL", DEFAULT_CONTROLLER_MODEL)

class ControllerAgent:
    """
    Agent 4: Applies the selected control prompts to the extracted text.
    """
    def __init__(self):
        logger.info(f"Initializing ControllerAgent with model: {CONTROLLER_MODEL_ID}")
        # Configure the LLM to use for applying controls
        self.llm_agent = Agent(
             model=OpenAIChat(id=CONTROLLER_MODEL_ID), # Use configured model ID
             # model=Claude(id=CONTROLLER_MODEL_ID), # Example: Use if model ID indicates Anthropic
             instructions=[
                 "You are a control verification assistant.",
                 "Execute the specific instruction provided for the control precisely.",
                 "Respond ONLY with the requested output format."
             ],
             markdown=False, # Adjust based on expected output format
             # Configure debug mode via env var (e.g., AGNO_DEBUG_MODE=true)
             debug_mode=os.getenv('AGNO_DEBUG_MODE', 'false').lower() == 'true'
         )
        logger.info("ControllerAgent initialized.")

    def run(self, text_chunks: List[str], prompt_files: list[str]) -> list[dict[str, Any]]:
        """
        Applies each control prompt to each chunk of extracted text using an LLM.
        Returns a flattened list of dictionaries, potentially multiple per control_id (one per chunk),
        each containing: {'id', 'description', 'instructions', 'result', 'chunk_index'}
        """
        if not text_chunks:
             logger.error("Received empty list of text chunks.")
             return []

        # Handle case where extractor returned an error message as the only chunk
        if len(text_chunks) == 1 and text_chunks[0].startswith("Error:"):
            logger.error(f"Received extraction error: {text_chunks[0]}")
            # Return a single error entry so the error is visible downstream.
            return [{
                'id': 'EXTRACTOR_ERROR',
                'description': 'Text extraction failed',
                'instructions': [],
                'result': text_chunks[0],
                'chunk_index': 0 # Add chunk index for clarity
            }]

        logger.info(f"Applying {len(prompt_files)} controls across {len(text_chunks)} text chunks...")
        detailed_results = []

        for prompt_file in prompt_files:
            control_id = os.path.basename(prompt_file).replace('.json', '') # Cleaner ID
            description = "N/A"
            instructions = []
            control_load_error = None # Track errors loading the prompt itself

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

            # If prompt loading failed, add one error entry for this control and skip chunks
            if control_load_error:
                 detailed_results.append({
                     'id': control_id,
                     'description': description,
                     'instructions': instructions,
                     'result': control_load_error,
                     'chunk_index': -1 # Indicate prompt load error
                 })
                 continue # Move to the next prompt file

            # Loop through each text chunk for the current prompt
            for i, chunk in enumerate(text_chunks):
                 logger.info(f"Applying control '{control_id}' to chunk {i+1}/{len(text_chunks)}...")
                 result_content_for_chunk = "Error: Processing failed before LLM call."
                 try:
                    # Construct the prompt for the LLM using the current chunk
                    full_prompt = (
                        f"Control Description: {description}\n"
                        f"Instructions:\n"
                        + "\n".join([f"- {inst}" for inst in instructions])
                        + "\n\n--- Document Text Chunk Start ---\n"
                        + chunk # Use the current chunk
                        + "\n--- Document Text Chunk End ---"
                    )
                    logger.debug(f"Running LLM for control '{control_id}' chunk {i}. Prompt length: {len(full_prompt)}")
                    # --- LLM Call ---
                    response = self.llm_agent.run(full_prompt, stream=False)

                    # --- Extract content ---
                    if hasattr(response, 'content') and response.content is not None:
                        result_content_for_chunk = str(response.content)
                    elif response:
                        result_content_for_chunk = "Error: Empty Response from LLM agent."
                        logger.warning(f"LLM response for '{control_id}' chunk {i} has no content.")
                    else:
                        result_content_for_chunk = "Error: No response object from LLM agent."
                        logger.error(f"No response object from LLM agent for '{control_id}' chunk {i}.")

                    log_snippet = result_content_for_chunk[:100].replace('\n', ' ') + ("..." if len(result_content_for_chunk) > 100 else "")
                    logger.info(f"Result for '{control_id}' chunk {i} received (snippet): {log_snippet}")

                 except Exception as llm_error:
                    logger.error(f"Error applying control '{control_id}' chunk {i} via LLM: {llm_error}", exc_info=True)
                    result_content_for_chunk = f"Error: LLM execution failed ({llm_error})"

                 # Append result for this specific chunk
                 detailed_results.append({
                     'id': control_id,
                     'description': description,
                     'instructions': instructions,
                     'result': result_content_for_chunk,
                     'chunk_index': i # Store chunk index
                 })
            # --- End of chunk loop ---
        # --- End of prompt loop ---

        logger.info(f"Finished applying controls. Total results generated: {len(detailed_results)}")
        return detailed_results
