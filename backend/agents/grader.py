import os
from typing import List, Dict, Any
from agno.agent import Agent
from agno.models.openai import OpenAIChat # Or other models
from agno.models.anthropic import Claude
import traceback

class GraderAgent:
    """
    Agent responsible for evaluating the risk level of control results using an LLM.
    """
    def __init__(self):
        # Initialize the LLM agent specifically for grading.
        # Consider using a cost-effective model if suitable.
        self.grade_llm = Agent(
            # model=OpenAIChat(id="gpt-3.5-turbo-instruct"), # Example
            model=OpenAIChat(id="gpt-4o-mini"), # Or same as controller
            instructions=[
                "You are an AI assistant evaluating the risk level of a control result based on the control's goal.",
                "Assess the risk level on a scale of 1 to 10, where 1 is very low risk (success/compliance) and 10 is very high risk (failure/non-compliance).",
                "Consider the control goal/instructions and the provided result.",
                "Output ONLY the integer score (1-10)."
            ],
            markdown=False,
            debug_mode=False # Set True to debug grader LLM calls
        )
        print("GraderAgent initialized.")

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
            return []

        print(f"GraderAgent: Grading {len(detailed_results)} results...")

        for item in detailed_results:
            control_id = item.get('id', 'UnknownID')
            instructions = item.get('instructions', [])
            description = item.get('description', '')
            result_text = item.get('result', '')

            # Use instructions if available, otherwise description as context
            grader_context = "\n".join(instructions) if instructions else description

            grade_prompt = (
                f"Control Goal/Instructions: {grader_context}\n\n"
                f"Control Result: {result_text}\n\n"
                f"Evaluate risk (1=low, 10=high). Output ONLY the integer score:"
            )

            score = -1 # Default score indicating grading failure
            try:
                print(f"GraderAgent: Getting score for {control_id}...")
                grade_response = self.grade_llm.run(grade_prompt, stream=False)

                if hasattr(grade_response, 'content') and grade_response.content:
                    llm_score_text = grade_response.content.strip()
                    try:
                        parsed_score = int(llm_score_text)
                        if 1 <= parsed_score <= 10:
                            score = parsed_score
                            print(f"GraderAgent: Score for {control_id}: {score}")
                        else:
                             print(f"GraderAgent Warning: Score for {control_id} out of range (1-10): {parsed_score}. Clamping to 10.")
                             score = 10 # Treat out-of-range as high risk
                    except ValueError:
                        print(f"GraderAgent Error: LLM returned non-integer score for {control_id}: '{llm_score_text}'. Assigning max risk (10).")
                        score = 10 # Assign max risk if parsing fails
                else:
                    print(f"GraderAgent Error: LLM returned empty response for {control_id}. Assigning max risk (10).")
                    score = 10 # Assign max risk if empty response

            except Exception as grade_error:
                 print(f"GraderAgent Error: LLM call failed for {control_id}: {grade_error}")
                 print(traceback.format_exc()) # Log detailed error for debugging
                 score = 10 # Assign max risk on LLM failure

            # Add the score to the dictionary
            item['score'] = score

        print(f"GraderAgent: Finished grading.")
        return detailed_results
