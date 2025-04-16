from agno.agent import Agent
from agno.team.team import Team # Potentially useful for complex orchestration
# Import other agents
from agents.extractor import ExtractorAgent
from agents.selector import SelectorAgent
from agents.controller import ControllerAgent
from agents.reporter import ReporterAgent
from agents.grader import GraderAgent

import os
import pathlib # Using pathlib for easier path manipulation
from typing import Optional, List, Dict, Any # <-- Added List, Dict, Any

# Updated list of known categories
KNOWN_META_CATEGORIES = ["KYC", "RGPD", "LCBFT", "MIFID", "RSE", "INTERNAL_REPORTING"] # Added MIFID, RSE

class OrchestratorAgent:
    """
    Agent 1: Orchestrates the control automation workflow.
    Determines document type and meta-category, then calls other agents.
    """
    def __init__(self):
        # Initialize sub-agents
        self.extractor = ExtractorAgent()
        self.selector = SelectorAgent(prompts_dir="prompts") # Point to prompts directory
        self.controller = ControllerAgent()
        self.reporter = ReporterAgent(report_dir="reports") # Point to reports directory
        self.grader = GraderAgent()

        # Optional: Initialize an Agno Agent for complex decision making if needed
        # Example: Use LLM to determine meta-category from filename or initial content snippet
        # self.classifier_agent = Agent(
        #     model=...,
        #     instructions=[
        #         "Given the document path and potentially a content snippet, determine the most relevant control meta-category.",
        #         f"Choose ONLY ONE from the following list: {', '.join(KNOWN_META_CATEGORIES)}"
        #     ]
        # )

    def determine_meta_category(self, document_path: str) -> str:
        """
        Determines the meta-category for the controls based on document path or content.
        Priority:
        1. Check immediate parent directory name.
        2. Check if category name exists anywhere in the path.
        3. Prompt user.
        Needs refinement based on actual use case.
        """
        abs_path = pathlib.Path(document_path).resolve()
        parent_dir_name = abs_path.parent.name

        # 1. Check immediate parent directory name (case-insensitive)
        for category in KNOWN_META_CATEGORIES:
            if parent_dir_name.lower() == category.lower():
                print(f"Orchestrator: Inferred category '{category}' from parent directory name.")
                return category

        # 2. Fallback: Check if category name is anywhere in the path (less precise)
        normalized_path_str = str(abs_path).replace("\\", "/").lower()
        for category in KNOWN_META_CATEGORIES:
            # Look for the category name surrounded by path separators or at the start/end
            # This is slightly more robust than the previous check
            pattern = f"/{category.lower()}/"
            if pattern in normalized_path_str:
                 print(f"Orchestrator: Inferred category '{category}' from full path.")
                 return category
            # Consider checks for start/end of path components if needed

        # 3. Fallback: Ask user
        print(f"Orchestrator: Could not infer category from path: {document_path}")
        print(f"Known categories: {KNOWN_META_CATEGORIES}")
        while True:
            try:
                print("Please select the control meta-category:")
                for i, cat in enumerate(KNOWN_META_CATEGORIES):
                    print(f"  {i+1}: {cat}")
                choice = input(f"Enter number (1-{len(KNOWN_META_CATEGORIES)}) or category name: ").strip()
                if choice.isdigit() and 1 <= int(choice) <= len(KNOWN_META_CATEGORIES):
                    selected_category = KNOWN_META_CATEGORIES[int(choice)-1]
                    print(f"Using selected category: {selected_category}")
                    return selected_category
                elif choice.upper() in KNOWN_META_CATEGORIES:
                     selected_category = choice.upper()
                     print(f"Using selected category: {selected_category}")
                     return selected_category
                else:
                    print("Invalid selection.")
            except (ValueError, IndexError):
                 print("Invalid input.")
            except EOFError: # Handle non-interactive execution
                 print("Orchestrator: Cannot prompt for category in non-interactive mode. Aborting.")
                 return ""
        # return "DEFAULT_CATEGORY" # Or raise ValueError("Could not determine meta-category")

    def run_control_chain(self, document_path: str, specified_meta_category: str | None = None) -> tuple[Optional[List[Dict[str, Any]]], Optional[str]]:
        """
        Executes the full chain of control automation for a single document.
        Returns a tuple: (detailed_results_with_scores: list[dict] | None, report_path: str | None)
        Where detailed_results contains {'id', 'description', 'instructions', 'result', 'score'}
        """
        print(f"--- Starting Control Chain for: {document_path} ---")
        detailed_results: Optional[List[Dict[str, Any]]] = None
        report_path: Optional[str] = None

        # 1. Determine Meta-Category (if not specified)
        if specified_meta_category and specified_meta_category.upper() in KNOWN_META_CATEGORIES:
            meta_category = specified_meta_category.upper()
            print(f"Orchestrator: Using specified category '{meta_category}'.")
        else:
            meta_category = self.determine_meta_category(document_path)
            if not meta_category:
                 print(f"Orchestrator: Failed to determine meta-category for {document_path}. Aborting chain.")
                 return None, None # Return None for both results and path

        # 2. Extract Text (Agent 2)
        extracted_text = self.extractor.run(document_path)
        if not extracted_text or extracted_text.startswith("Error:"):
            print(f"Orchestrator: Failed to extract text from {document_path}. Aborting chain.")
            # Optionally create and return path to a failure report
            failure_reason = {"status": f"Failed: {extracted_text or 'Unknown extraction error'}"}
            report_path = self.reporter.run(document_path, failure_reason, is_failure=True)
            print(f"--- Control Chain Failed (Extraction). Report: {report_path} ---")
            return None, report_path # Return None for results

        # 3. Select Prompts (Agent 3)
        prompt_files = self.selector.run(meta_category)
        if not prompt_files:
            print(f"Orchestrator: No prompts found for category '{meta_category}'. Aborting controls, but generating report.")
            # Create a single result indicating the skip
            detailed_results = [{
                'id': f'SKIP_{meta_category}',
                'description': 'Control execution skipped',
                'instructions': [],
                'result': f"No prompts found for category '{meta_category}'"
            }]
            report_path = self.reporter.run(document_path, {"status": detailed_results[0]['result']}) # Use the status in the simple report for now
            print(f"--- Finished Control Chain (No Prompts). Report: {report_path} ---")
            # Return the results list indicating skip, and the report path
            return detailed_results, report_path

        # 4. Apply Controls (Agent 4) - Now returns a list
        detailed_results_no_score = self.controller.run(extracted_text, prompt_files)
        if not detailed_results_no_score:
             print("Orchestrator: Controller returned no results. Generating report.")
             detailed_results = [{
                 'id': f'FAIL_CONTROLLER_{meta_category}',
                 'description': 'Controller execution failed',
                 'instructions': [],
                 'result': 'Controller agent returned empty results list.',
                 'score': 10
             }]
        else:
            # 4.5. Grade Results (GraderAgent)
            print("Orchestrator: Handing off results to GraderAgent...")
            detailed_results = self.grader.run(detailed_results_no_score)
            # detailed_results now contains the 'score' key for each item

        # 5. Create Report (ReporterAgent)
        # The reporter might need adjustment if we want the full detailed_results in the report,
        # but for now, it likely takes a simple dict. Let's pass a summary dict derived from detailed_results.
        # TODO: Revisit reporter input if needed.
        # simple_results_for_report = {item['id']: item['result'] for item in detailed_results} if detailed_results else {}
        # report_path = self.reporter.run(document_path, simple_results_for_report)

        # --- Updated: Pass the full detailed_results list (with scores) to the reporter ---
        # Handle cases where detailed_results might be None (e.g., extraction failure handled earlier)
        if detailed_results is None:
             # If results are None but we reached here, it implies an earlier failure
             # (e.g., extraction) already generated a report path. We should return that.
             # The earlier logic should have already set report_path and returned.
             # This case should ideally not be reached if prior logic is correct.
             print("Orchestrator Warning: Reached reporting stage with None results, likely an issue.")
             # We already returned (None, report_path) in the extraction failure case.
             # If category determination failed, we returned (None, None).
             # If no prompts, we created a dummy detailed_results and will proceed.
             # If controller failed, we created a dummy detailed_results and will proceed.
             # So, if detailed_results is None here, something is wrong, but we pass empty list.
             detailed_results_for_report = []
        else:
             detailed_results_for_report = detailed_results

        # Pass the list (potentially empty or dummy) to the reporter
        report_path = self.reporter.run(document_path, detailed_results_for_report)

        print(f"--- Finished Control Chain for: {document_path}. Report: {report_path} ---")

        # Return the detailed results list (including scores) and the report path
        return detailed_results, report_path
