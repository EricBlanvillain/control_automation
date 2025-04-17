import logging
import os
import pathlib # Using pathlib for easier path manipulation
import re # Import regex for keyword matching
from typing import Optional, List, Dict, Any # <-- Added List, Dict, Any
from agno.agent import Agent
from agno.team.team import Team # Potentially useful for complex orchestration
# Import other agents
from agents.extractor import ExtractorAgent
from agents.selector import SelectorAgent
from agents.controller import ControllerAgent
from agents.reporter import ReporterAgent
from agents.grader import GraderAgent
import chromadb # Import chromadb type hint

# --- Basic Logging Setup ---
# REMOVED redundant basicConfig - logging should be configured in api_server.py
# log_level_str = os.getenv('LOG_LEVEL', 'INFO').upper()
# log_level = getattr(logging, log_level_str, logging.INFO)
# logging.basicConfig(level=log_level,
#                     format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)
# --- End Removal ---

# --- Configuration ---
# Load known categories from environment or use defaults
DEFAULT_CATEGORIES = "KYC,RGPD,LCBFT,MIFID,RSE,INTERNAL_REPORTING" # Default list
KNOWN_META_CATEGORIES = [cat.strip() for cat in os.getenv("KNOWN_META_CATEGORIES", DEFAULT_CATEGORIES).split(',') if cat.strip()]

logger.info(f"Orchestrator: Using known categories: {KNOWN_META_CATEGORIES}")

# Basic keyword mapping for content-based detection (Case-insensitive)
# This is very basic and likely needs significant refinement
CATEGORY_KEYWORDS = {
    "KYC": [r'know your customer', r'\bkyc\b', r'client identification', r'due diligence'],
    "RGPD": [r'general data protection regulation', r'\brgpd\b', r'\bgdpr\b', r'personal data', r'data privacy', r'consentement', r'données personnelles'],
    "LCBFT": [r'lutte contre le blanchiment', r'financement du terrorisme', r'\blcb.?ft\b', r'aml', r'anti.?money laundering'],
    "MIFID": [r'markets in financial instruments directive', r'\bmifid\b', r'financial instrument', r'investment advice', r'appropriateness'],
    "RSE": [r'responsabilité sociale des entreprises', r'\brse\b', r'csr', r'corporate social responsibility', r'environmental', r'social', r'governance', r'esg'],
    "INTERNAL_REPORTING": [r'internal report', r'monthly summary', r'activity log', r'management update']
}

class OrchestratorAgent:
    """
    Agent 1: Orchestrates the control automation workflow.
    Determines meta-category (path or content), then calls other agents.
    """
    def __init__(self):
        logger.info("Initializing OrchestratorAgent...")
        # Initialize sub-agents
        # Agents now read their own config (dirs, models) from env vars or defaults
        self.extractor = ExtractorAgent()
        self.selector = SelectorAgent()
        self.controller = ControllerAgent()
        self.reporter = ReporterAgent()
        self.grader = GraderAgent()
        logger.info("OrchestratorAgent initialized with sub-agents.")

        # Optional: Initialize an Agno Agent for complex decision making if needed
        # Example: Use LLM to determine meta-category from filename or initial content snippet
        # self.classifier_agent = Agent(
        #     model=...,
        #     instructions=[
        #         "Given the document path and potentially a content snippet, determine the most relevant control meta-category.",
        #         f"Choose ONLY ONE from the following list: {', '.join(KNOWN_META_CATEGORIES)}"
        #     ]
        # )

    def _determine_category_from_path(self, document_path: str) -> str:
        """
        Determines category based purely on document path.
        Priority: Parent directory name, then anywhere in path.
        Returns category name or empty string if no match.
        """
        logger.debug(f"Attempting path-based category detection for: {document_path}")
        try:
            abs_path = pathlib.Path(document_path).resolve()
            parent_dir_name = abs_path.parent.name

            # 1. Check immediate parent directory name (case-insensitive)
            for category in KNOWN_META_CATEGORIES:
                if parent_dir_name.lower() == category.lower():
                    logger.info(f"Path Detection: Found category '{category}' from parent directory.")
                    return category

            # 2. Fallback: Check if category name is anywhere in the path (case-insensitive)
            normalized_path_str = str(abs_path).replace("\\", "/").lower()
            for category in KNOWN_META_CATEGORIES:
                pattern = f"/{category.lower()}/"
                if pattern in normalized_path_str:
                     logger.info(f"Path Detection: Found category '{category}' from full path.")
                     return category

            logger.info(f"Path Detection: No category match found for path: {document_path}")
            return ""
        except Exception as e:
             logger.error(f"Path Detection: Error processing path {document_path}: {e}", exc_info=True)
             return ""

    def _determine_category_from_content(self, text_chunk: str) -> str:
        """
        Attempts to determine category based on keywords in a text chunk.
        Returns the first matching category or empty string.
        """
        if not text_chunk:
            logger.warning("Content Detection: Received empty text chunk.")
            return ""

        logger.info(f"Attempting content-based category detection (basic keywords) on chunk (length {len(text_chunk)})...")
        text_lower = text_chunk.lower()

        # Iterate through categories and their keywords
        for category, keywords in CATEGORY_KEYWORDS.items():
            if category not in KNOWN_META_CATEGORIES:
                 logger.warning(f"Content Detection: Keyword category '{category}' not in known list. Skipping.")
                 continue
            for keyword_pattern in keywords:
                try:
                    if re.search(keyword_pattern, text_lower):
                        logger.info(f"Content Detection: Found category '{category}' based on keyword '{keyword_pattern}'.")
                        return category
                except re.error as e:
                     logger.error(f"Content Detection: Invalid regex pattern '{keyword_pattern}' for category '{category}': {e}")
                     # Optionally break or continue to next pattern/category

        logger.info("Content Detection: No category match found based on keywords.")
        return ""

    def run_control_chain(self, document_path: str, specified_meta_category: str | None = None) -> tuple[Optional[List[Dict[str, Any]]], Optional[str]]:
        """
        Executes the full chain of control automation for a single document.
        Includes path and fallback content-based category detection.
        Uses vector store for relevant chunk retrieval.
        """
        logger.info(f"--- Starting Control Chain for: {document_path} ---")
        report_path: Optional[str] = None
        meta_category = ""
        vector_collection: Optional[chromadb.Collection] = None # Initialize collection variable

        # 1. Determine Meta-Category (Path-based)
        # 1a. Use specified category if valid
        if specified_meta_category:
            valid_specified_category = specified_meta_category.upper()
            if valid_specified_category in KNOWN_META_CATEGORIES:
                meta_category = valid_specified_category
                logger.info(f"Using specified category '{meta_category}'.")
            else:
                 logger.warning(f"Specified category '{specified_meta_category}' is not in known list {KNOWN_META_CATEGORIES}. Attempting auto-detection.")

        # 1b. Try path-based detection if not specified or invalid
        if not meta_category:
            meta_category = self._determine_category_from_path(document_path)

        # --- Extraction & Embedding (now returns a collection or None) --- #
        logger.info(f"Running ExtractorAgent for document: {document_path}")
        # Extractor now returns (collection, error_msg)
        vector_collection, extraction_error_msg = self.extractor.run(document_path)

        # Handle extraction/embedding failure
        if extraction_error_msg:
            logger.error(f"Extraction or Embedding failed: {extraction_error_msg}")
            # Handle cleanup if needed (e.g., delete partial collection if extractor didn't)
            # Note: Extractor currently attempts cleanup on its errors.
            report_path = self.reporter.run(document_path, [{'id': 'EXTRACTION_EMBED_FAILURE', 'result': extraction_error_msg, 'score': 10}], is_failure=True)
            logger.error(f"--- Control Chain Failed (Extraction/Embedding). Report: {report_path} ---")
            return None, report_path
        # Handle case where extraction was technically successful but yielded no processable content
        elif vector_collection is None:
             # This can happen if the file was empty or extraction yielded nothing before embedding
             logger.warning(f"Extractor returned no vector collection (likely no content found) for {document_path}. Cannot apply controls.")
             no_content_msg = f"Extraction successful, but no text content found or embedded in {document_path}. Cannot apply controls."
             detailed_results = [{'id': 'NO_CONTENT', 'description': 'Extraction yielded no content', 'instructions': [], 'result': no_content_msg, 'score': 0}]
             report_path = self.reporter.run(document_path, detailed_results)
             logger.info(f"--- Finished Control Chain (No Content Found). Report: {report_path} ---")
             return detailed_results, report_path

        # 1c. Try content-based detection if path detection failed (requires reading from collection)
        if not meta_category:
             try:
                 # Get the first chunk from the collection for content detection
                 # Note: This might not be the *best* chunk, but it's a starting point.
                 # Consider getting a few chunks or a summary if this proves unreliable.
                 first_chunk_result = vector_collection.peek(limit=1)
                 if first_chunk_result and first_chunk_result.get('documents') and first_chunk_result['documents'][0]:
                     first_chunk_text = first_chunk_result['documents'][0]
                     logger.info("Path detection failed, attempting content-based detection on first chunk from vector store.")
                     meta_category = self._determine_category_from_content(first_chunk_text)
                 else:
                      logger.warning("Path detection failed, and could not retrieve first chunk from vector store for content detection.")
             except Exception as e:
                  logger.error(f"Error retrieving first chunk from vector store for content detection: {e}", exc_info=True)
                  # Continue without content detection if retrieval fails

        # 1d. Final check: Handle failure to determine category
        if not meta_category:
             failure_msg = f"Could not determine a valid control category for {document_path} after path and content checks. Known: {KNOWN_META_CATEGORIES}"
             logger.error(failure_msg)
             report_path = self.reporter.run(document_path, [{'id': 'CATEGORY_FAILURE', 'result': failure_msg, 'score': 10}], is_failure=True)
             logger.error(f"--- Control Chain Failed (Category Determination). Report: {report_path} ---")
             # Cleanup the created collection since we're failing
             try:
                 logger.info(f"Attempting to delete unused collection: {vector_collection.name}")
                 self.extractor.chroma_client.delete_collection(vector_collection.name)
             except Exception as e:
                 logger.error(f"Failed to delete collection {vector_collection.name} on category failure: {e}")
             return None, report_path

        # --- Proceed with Control Chain using the determined category and vector collection --- #

        # 3. Select Prompts
        logger.info(f"Running SelectorAgent for category: {meta_category}")
        prompt_files = self.selector.run(meta_category)
        if not prompt_files:
            no_prompts_msg = f"No valid prompts found for category '{meta_category}'."
            logger.warning(no_prompts_msg)
            detailed_results = [{'id': f'SKIP_{meta_category}', 'description': 'Control execution skipped (no valid prompts)', 'instructions': [], 'result': no_prompts_msg, 'score': 0}]
            report_path = self.reporter.run(document_path, detailed_results)
            logger.info(f"--- Finished Control Chain (No Valid Prompts Found). Report: {report_path} ---")
            # Cleanup collection
            try:
                logger.info(f"Attempting to delete unused collection: {vector_collection.name}")
                self.extractor.chroma_client.delete_collection(vector_collection.name)
            except Exception as e:
                logger.error(f"Failed to delete collection {vector_collection.name} on prompt skip: {e}")
            return detailed_results, report_path

        # --- Check Vector Collection Type before proceeding ---
        if not isinstance(vector_collection, chromadb.Collection):
             error_msg = f"Internal Error: Expected vector_collection to be a ChromaDB Collection, but got {type(vector_collection)}."
             logger.error(error_msg)
             # Attempt cleanup if collection object exists somehow (though unlikely)
             if hasattr(vector_collection, 'name'):
                  try:
                      self.extractor.chroma_client.delete_collection(vector_collection.name)
                  except Exception as e:
                       logger.error(f"Error during cleanup on type mismatch: {e}")
             report_path = self.reporter.run(document_path, [{'id': 'INTERNAL_ERROR', 'result': error_msg, 'score': 10}], is_failure=True)
             return None, report_path
        # --- End Check ---

        # 4. Apply Controls (using vector collection)
        # Controller now takes the collection instead of text_chunks
        logger.info(f"Running ControllerAgent with {len(prompt_files)} prompts using vector collection: {vector_collection.name}")
        detailed_results_no_score = self.controller.run(vector_collection, prompt_files) # Pass collection

        # --- Cleanup Collection ---
        # Delete the collection after ControllerAgent is done with it
        # The check above ensures vector_collection is a Collection here
        try:
             logger.info(f"Attempting to delete used collection: {vector_collection.name}")
             self.extractor.chroma_client.delete_collection(vector_collection.name)
             logger.info(f"Successfully deleted collection: {vector_collection.name}")
        except Exception as e:
             # If vector_collection was confirmed to be a Collection, .name access here should be safe
             # Error is likely in the delete operation itself.
             logger.error(f"Failed to delete collection {getattr(vector_collection, 'name', '[unknown]')} after processing: {e}", exc_info=True)
             # Log error but continue with reporting

        # --- Process Results ---
        if not detailed_results_no_score:
             controller_fail_msg = "Controller agent returned empty results list."
             logger.error(controller_fail_msg)
             detailed_results = [{'id': f'FAIL_CONTROLLER_{meta_category}', 'description': 'Controller execution failed', 'instructions': [], 'result': controller_fail_msg, 'score': 10}]
        else:
            # 4.5. Grade Results
            logger.info(f"Running GraderAgent on {len(detailed_results_no_score)} results.")
            detailed_results = self.grader.run(detailed_results_no_score) # Grader might need adjustment later

        # 5. Create Report
        logger.info("Running ReporterAgent...")
        report_path = self.reporter.run(document_path, detailed_results) # Reporter might need adjustment later

        logger.info(f"--- Finished Control Chain for: {document_path}. Report: {report_path} ---")
        return detailed_results, report_path
