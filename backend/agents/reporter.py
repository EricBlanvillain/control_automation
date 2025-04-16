import os
import datetime
from typing import List, Dict, Any # <-- Add imports
# from agno.agent import Agent # No longer using Agno directly here

class ReporterAgent:
    """
    Agent 5: Creates a final report summarizing the control results.
    """
    def __init__(self, report_dir: str = "reports"):
        self.report_dir = report_dir
        os.makedirs(self.report_dir, exist_ok=True) # Ensure report dir exists
        # Placeholder for now

    def run(self, original_document_path: str,
            detailed_results: List[Dict[str, Any]], # <-- Changed type hint
            is_failure: bool = False) -> str:
        """
        Generates a report file summarizing the results, including scores.
        Returns the path to the generated report file, or empty string on failure.
        If is_failure is True, indicates the report is for a process failure (e.g., extraction).
        """
        print("Reporter: Generating report...")
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        original_filename = os.path.basename(original_document_path)
        base_report_name = os.path.splitext(original_filename)[0] if original_filename else "document"
        report_prefix = "FAILURE_report" if is_failure else "report"
        report_filename = f"{report_prefix}_{base_report_name}_{timestamp}.txt"
        report_path = os.path.join(self.report_dir, report_filename)

        try:
            with open(report_path, 'w', encoding='utf-8', newline='\n') as f:
                f.write("--- Control Automation Report ---\n\n")
                f.write(f"Original Document: {original_document_path}\n")
                f.write(f"Report Generated: {datetime.datetime.now().isoformat()}\n")
                # Note: Summary section is now added later by the API endpoint logic
                f.write("\n--- Control Results ---\n\n")

                if not detailed_results:
                    # Check if it was a failure report (e.g., extraction failed)
                    if is_failure:
                         f.write("Process failed before controls could be run.\nDetails: See logs or error message.\n")
                    else:
                         f.write("No controls were applied or results available.\n")
                else:
                    for item in detailed_results:
                        control_id = item.get('id', 'UnknownID')
                        score = item.get('score', 'N/A') # Get score, default to N/A
                        result_str = str(item.get('result', '')) # Get result

                        # Write ID line including the score in the desired format
                        f.write(f"Control ID: {control_id} (Risk Score: {score}/10)\n")
                        # Write result line
                        f.write(f"Result: {result_str}\n")
                        f.write("-" * 20 + "\n") # Separator line

                f.write("\n--- End of Report ---\n")

            print(f"Reporter: Report saved to {report_path}")
            return report_path

        except Exception as e:
            print(f"Reporter: Failed to write report {report_path}: {e}")
            return ""
