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

# --- Basic Logging Setup ---
# This should ideally be configured once in the main application entry point (e.g., api_server.py)
# Basic config to get logs printed to console. Level INFO or DEBUG based on env var.
log_level_str = os.getenv('LOG_LEVEL', 'INFO').upper()
log_level = getattr(logging, log_level_str, logging.INFO)
logging.basicConfig(level=log_level,
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

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
        """
        logger.info(f"--- Starting Control Chain for: {document_path} ---")
        report_path: Optional[str] = None
        meta_category = ""

        # 1. Determine Meta-Category
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

        # --- Extraction (needed for content detection fallback and main process) --- #
        logger.info(f"Running ExtractorAgent for document: {document_path}")
        text_chunks, extraction_error_msg = self.extractor.run(document_path)

        # Handle extraction failure *before* content detection fallback
        if extraction_error_msg:
            logger.error(f"Extraction failed: {extraction_error_msg}")
            report_path = self.reporter.run(document_path, [{'id': 'EXTRACTION_FAILURE', 'result': extraction_error_msg, 'score': 10}], is_failure=True)
            logger.error(f"--- Control Chain Failed (Extraction). Report: {report_path} ---")
            return None, report_path
        elif text_chunks is None: # Defensive check
             logger.error("Extractor returned None chunks without an error message. Treating as failure.")
             report_path = self.reporter.run(document_path, [{'id': 'EXTRACTION_FAILURE', 'result': 'Unknown extraction error (None chunks)', 'score': 10}], is_failure=True)
             logger.error(f"--- Control Chain Failed (Extraction). Report: {report_path} ---")
             return None, report_path

        # 1c. Try content-based detection if path detection failed and extraction worked
        if not meta_category:
             if text_chunks: # Check if we have content to analyze
                 logger.info("Path detection failed, attempting content-based detection on first chunk.")
                 meta_category = self._determine_category_from_content(text_chunks[0])
             else:
                  logger.warning("Path detection failed, and no content extracted. Cannot attempt content-based detection.")

        # 1d. Final check: Handle failure to determine category after all attempts
        if not meta_category:
             failure_msg = f"Could not determine a valid control category for {document_path}. Path and content detection failed. Known: {KNOWN_META_CATEGORIES}"
             logger.error(failure_msg)
             report_path = self.reporter.run(document_path, [{'id': 'CATEGORY_FAILURE', 'result': failure_msg, 'score': 10}], is_failure=True)
             logger.error(f"--- Control Chain Failed (Category Determination). Report: {report_path} ---")
             return None, report_path

        # --- Proceed with Control Chain using the determined category --- #

        # Handle case: No text content extracted (but extraction didn't fail)
        if not text_chunks:
             no_content_msg = f"Extraction successful, but no text content found in {document_path}. Cannot apply controls."
             logger.warning(no_content_msg)
             detailed_results = [{'id': 'NO_CONTENT', 'description': 'Extraction yielded no content', 'instructions': [], 'result': no_content_msg, 'score': 0}]
             report_path = self.reporter.run(document_path, detailed_results)
             logger.info(f"--- Finished Control Chain (No Content Found). Report: {report_path} ---")
             return detailed_results, report_path

        # 3. Select Prompts
        logger.info(f"Running SelectorAgent for category: {meta_category}")
        prompt_files = self.selector.run(meta_category)
        if not prompt_files:
            no_prompts_msg = f"No valid prompts found for category '{meta_category}'."
            logger.warning(no_prompts_msg)
            detailed_results = [{'id': f'SKIP_{meta_category}', 'description': 'Control execution skipped (no valid prompts)', 'instructions': [], 'result': no_prompts_msg, 'score': 0}]
            report_path = self.reporter.run(document_path, detailed_results)
            logger.info(f"--- Finished Control Chain (No Valid Prompts Found). Report: {report_path} ---")
            return detailed_results, report_path

        # 4. Apply Controls
        logger.info(f"Running ControllerAgent with {len(prompt_files)} prompts on {len(text_chunks)} chunks.")
        detailed_results_no_score = self.controller.run(text_chunks, prompt_files)
        if not detailed_results_no_score:
             controller_fail_msg = "Controller agent returned empty results list."
             logger.error(controller_fail_msg)
             detailed_results = [{'id': f'FAIL_CONTROLLER_{meta_category}', 'description': 'Controller execution failed', 'instructions': [], 'result': controller_fail_msg, 'score': 10}]
        else:
            # 4.5. Grade Results
            logger.info(f"Running GraderAgent on {len(detailed_results_no_score)} results.")
            detailed_results = self.grader.run(detailed_results_no_score)

        # 5. Create Report
        logger.info("Running ReporterAgent...")
        report_path = self.reporter.run(document_path, detailed_results)

        logger.info(f"--- Finished Control Chain for: {document_path}. Report: {report_path} ---")
        return detailed_results, report_path
