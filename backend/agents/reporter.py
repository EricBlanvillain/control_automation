import os
import datetime
import logging
from typing import List, Dict, Any, Tuple
# from agno.agent import Agent # No longer using Agno directly here

# Set up logger
logger = logging.getLogger(__name__)

# Define score threshold for passing
PASS_SCORE_THRESHOLD = 5

class ReporterAgent:
    """
    Agent 5: Creates a final report summarizing the control results.
    Includes a pass/fail summary and control descriptions.
    """
    def __init__(self, report_dir: str | None = None):
        # Use provided dir, env variable, or default
        self.report_dir = report_dir or os.getenv("REPORTS_DIR", "reports")
        logger.info(f"ReporterAgent initialized. Using report directory: {self.report_dir}")
        try:
             os.makedirs(self.report_dir, exist_ok=True) # Ensure report dir exists
        except OSError as e:
             logger.error(f"Failed to create report directory {self.report_dir}: {e}", exc_info=True)
             # Depending on requirements, might want to raise the error here

    def _calculate_summary(self, consolidated_results: Dict[str, Dict[str, Any]]) -> Tuple[int, int, int]:
        """Calculates pass/fail counts based on consolidated scores."""
        passed_count = 0
        failed_count = 0
        total_controls = len(consolidated_results)

        for control_id, result_data in consolidated_results.items():
            score = result_data.get('score') # This is the original score from the worst item
            if isinstance(score, (int, float)) and 1 <= score < PASS_SCORE_THRESHOLD:
                passed_count += 1
            else:
                # Failed if score >= threshold, or if score is invalid/error (-1, 0, N/A, etc.)
                failed_count += 1
                logger.debug(f"Control '{control_id}' counted as failed (Score: {score})")

        return passed_count, failed_count, total_controls

    def run(self, original_document_path: str,
            detailed_results: List[Dict[str, Any]], # List of results, potentially multiple per control
            is_failure: bool = False) -> str:
        """
        Generates a report file summarizing the results, including scores and descriptions.
        Consolidates results for the same control ID based on the highest risk score.
        Includes a Pass/Fail summary at the top.
        Returns the path to the generated report file, or empty string on failure.
        """
        logger.info("Generating consolidated report...")
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        original_filename = os.path.basename(original_document_path)
        base_report_name = os.path.splitext(original_filename)[0] if original_filename else "document"
        report_prefix = "FAILURE_report" if is_failure else "report"
        report_filename = f"{report_prefix}_{base_report_name}_{timestamp}.txt"
        report_path = os.path.join(self.report_dir, report_filename)

        # --- Consolidate Results --- #
        # Group results by control ID first
        results_by_id: Dict[str, List[Dict[str, Any]]] = {}
        if detailed_results:
             for item in detailed_results:
                 control_id = item.get('id', 'UnknownID')
                 # Skip special markers unless it's a failure report
                 if not is_failure and control_id in ['EXTRACTOR_ERROR', 'CATEGORY_FAILURE', 'NO_CONTENT']:
                      logger.debug(f"Skipping special marker '{control_id}' in normal report consolidation.")
                      continue
                 if control_id.startswith('SKIP_'): # Also skip skip markers
                      logger.debug(f"Skipping skip marker '{control_id}' in normal report consolidation.")
                      continue
                 if control_id not in results_by_id:
                     results_by_id[control_id] = []
                 results_by_id[control_id].append(item)

        # Consolidate based on highest risk score
        consolidated_data: Dict[str, Dict[str, Any]] = {}
        for control_id, items in results_by_id.items():
            worst_item = None
            max_risk_score_value = -1
            for item in items:
                score = item.get('score', -1)
                current_risk_for_comparison = 10 # Default to max risk for errors/invalid
                if isinstance(score, (int, float)) and 1 <= score <= 10:
                     current_risk_for_comparison = score # Valid score

                if current_risk_for_comparison >= max_risk_score_value:
                     if current_risk_for_comparison > max_risk_score_value or worst_item is None:
                         max_risk_score_value = current_risk_for_comparison
                         worst_item = item
                elif worst_item is None:
                     worst_item = item # Keep first item if no valid scores

            if worst_item:
                 consolidated_data[control_id] = worst_item # Store the item with the highest risk
            else:
                 # This case should ideally not happen if results_by_id has entries
                 logger.error(f"Could not determine worst_item for control_id '{control_id}' during consolidation.")

        # --- Generate Report --- #
        try:
            with open(report_path, 'w', encoding='utf-8', newline='\n') as f:
                f.write("--- Control Automation Report ---\n\n")
                f.write(f"Original Document: {original_document_path}\n")
                f.write(f"Report Generated: {datetime.datetime.now().isoformat()}\n")

                # --- Summary Section --- #
                f.write("\n--- Summary ---\n")
                if is_failure:
                    f.write("Status: PROCESS FAILED (See details below or logs)\n")
                elif not consolidated_data and not results_by_id: # No valid controls were run or yielded results
                    # Check original detailed_results for special markers like NO_CONTENT or SKIP
                    no_data_reason = "No applicable controls found or executed."
                    if detailed_results:
                         first_result_id = detailed_results[0].get('id', '')
                         if first_result_id == 'NO_CONTENT':
                              no_data_reason = "Extraction yielded no content."
                         elif first_result_id.startswith('SKIP_'):
                              no_data_reason = f"Control execution skipped: {detailed_results[0].get('result', 'No valid prompts found.')}"

                    f.write(f"Status: {no_data_reason}\n")
                    f.write("Controls Checked: 0\n")
                    f.write("Controls Passed: 0 / 0\n")
                else: # Some controls were consolidated
                    passed, failed, total = self._calculate_summary(consolidated_data)
                    status = "PASSED" if failed == 0 else f"FAILED ({failed} issues)"
                    f.write(f"Status: {status}\n")
                    f.write(f"Controls Checked: {total}\n")
                    f.write(f"Controls Passed: {passed} / {total}\n")
                    f.write(f"Controls Failed: {failed} / {total}\n")
                # --- End Summary --- #

                f.write("\n--- Detailed Results (Consolidated by Highest Risk) ---\n")

                if not consolidated_data:
                    if not is_failure:
                         # Reason should be covered in summary section
                         f.write("(No control results to display)\n")
                    else:
                         # If it's a failure report, show the failure reason if available
                         failure_detail = "Process failure reason not captured in results."
                         if detailed_results: # Check if the original list had the failure info
                              failure_detail = detailed_results[0].get('result', failure_detail)
                         f.write(f"Failure Reason: {failure_detail}\n")
                else:
                    # Process each unique control ID from consolidated data
                    for control_id, worst_item in sorted(consolidated_data.items()):
                        # Determine score display string
                        display_score_str = "N/A"
                        score = worst_item.get('score', 'N/A')
                        if isinstance(score, (int, float)) and 1 <= score <= 10:
                            display_score_str = f"{score}/10"
                        elif isinstance(score, (int, float)):
                            display_score_str = f"Error ({score})"
                        else:
                            display_score_str = "Invalid"

                        # Determine Pass/Fail status string for clarity
                        status_str = "FAIL"
                        if isinstance(score, (int, float)) and 1 <= score < PASS_SCORE_THRESHOLD:
                             status_str = "PASS"

                        result_str = str(worst_item.get('result', ''))
                        description_str = worst_item.get('description', 'N/A')

                        f.write(f"\nControl ID: {control_id}\n")
                        f.write(f"Status: {status_str} (Score: {display_score_str})\n")
                        f.write(f"Description: {description_str}\n")
                        f.write(f"Result (from highest risk instance):\n{result_str}\n")
                        f.write("-" * 30 + "\n") # Slightly longer separator

                f.write("\n\n--- End of Report ---\n")

            logger.info(f"Report saved to {report_path}")
            return report_path

        except Exception as e:
            logger.error(f"Failed to write report {report_path}: {e}", exc_info=True)
            return ""
