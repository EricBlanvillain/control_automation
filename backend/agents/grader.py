import os
from typing import List, Dict, Any
import logging
from agno.agent import Agent
from agno.models.openai import OpenAIChat # Or other models
from agno.models.anthropic import Claude
import traceback

# Set up logger
logger = logging.getLogger(__name__)

# --- Configuration ---
# Read model ID from environment variable or use default
DEFAULT_GRADER_MODEL = "gpt-4.1-nano" # Default model
GRADER_MODEL_ID = os.getenv("GRADER_LLM_MODEL", DEFAULT_GRADER_MODEL)

class GraderAgent:
    """
    Agent responsible for evaluating the risk level of control results using an LLM.
    """
    def __init__(self):
        # Initialize the LLM agent specifically for grading.
        logger.info(f"Initializing GraderAgent with model: {GRADER_MODEL_ID}")
        # TODO: Add logic to select model provider (OpenAI/Anthropic) based on model ID if needed
        self.grade_llm = Agent(
            model=OpenAIChat(id=GRADER_MODEL_ID), # Use configured model ID
            # model=Claude(id=GRADER_MODEL_ID), # Example: Use if model ID indicates Anthropic
            instructions=[
                "You are an AI assistant evaluating the risk level of a control result based on the control's goal.",
                "Assess the risk level on a scale of 1 to 10, where 1 is very low risk (success/compliance) and 10 is very high risk (failure/non-compliance).",
                "Consider the control goal/instructions and the provided result.",
                "Output ONLY the integer score (1-10)."
            ],
            markdown=False,
            # Configure debug mode via env var (e.g., AGNO_DEBUG_MODE=true)
            debug_mode=os.getenv('AGNO_DEBUG_MODE', 'false').lower() == 'true'
        )
        logger.info("GraderAgent initialized.")

    def run(self, detailed_results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Takes a list of detailed control results and adds a 'score' key to each dictionary
        based on LLM evaluation.

        Args:
            detailed_results: List of dicts, each containing 'id', 'description', 'instructions', 'result'.

        Returns:
            The same list of dicts, but each dict now includes a 'score' (int 1-10, or -1 if grading failed).
        """
        if not detailed_results:
            logger.warning("GraderAgent received empty list for grading. Returning empty.")
            return []

        logger.info(f"Grading {len(detailed_results)} results...")

        for item in detailed_results:
            control_id = item.get('id', 'UnknownID')
            instructions = item.get('instructions', [])
            description = item.get('description', '')
            result_text = item.get('result', '')

            # Use instructions if available, otherwise description as context
            grader_context = "\n".join(instructions) if instructions else description
            if not grader_context:
                 logger.warning(f"No grading context (instructions or description) found for {control_id}. Grading might be less accurate.")
            if not result_text:
                 logger.warning(f"No result text found for {control_id}. Grading might be less accurate.")

            grade_prompt = (
                f"Control Goal/Instructions: {grader_context}\n\n"
                f"Control Result: {result_text}\n\n"
                f"Evaluate risk (1=low, 10=high). Output ONLY the integer score:"
            )

            score = -1 # Default score indicating grading failure
            try:
                logger.info(f"Getting score for {control_id}...")
                grade_response = self.grade_llm.run(grade_prompt, stream=False)

                if hasattr(grade_response, 'content') and grade_response.content:
                    llm_score_text = grade_response.content.strip()
                    try:
                        parsed_score = int(llm_score_text)
                        if 1 <= parsed_score <= 10:
                            score = parsed_score
                            logger.info(f"Score for {control_id}: {score}")
                        else:
                             logger.warning(f"Score for {control_id} out of range (1-10): {parsed_score}. Clamping to 10.")
                             score = 10 # Treat out-of-range as high risk
                    except ValueError:
                        logger.error(f"LLM returned non-integer score for {control_id}: '{llm_score_text}'. Assigning max risk (10).")
                        score = 10 # Assign max risk if parsing fails
                else:
                    logger.error(f"LLM returned empty/invalid response for {control_id}. Assigning max risk (10).")
                    score = 10 # Assign max risk if empty response

            except Exception as grade_error:
                 logger.error(f"LLM call failed for {control_id}: {grade_error}", exc_info=True)
                 # Log detailed error for debugging - exc_info=True handles traceback
                 score = 10 # Assign max risk on LLM failure

            # Add the score to the dictionary
            item['score'] = score

        logger.info(f"Finished grading.")
        return detailed_results
