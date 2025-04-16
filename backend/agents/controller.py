from agno.agent import Agent
from agno.models.openai import OpenAIChat # Example model
from agno.models.anthropic import Claude   # Example model
import json
import os
from typing import Any

class ControllerAgent:
    """
    Agent 4: Applies the selected control prompts to the extracted text.
    """
    def __init__(self):
        # TODO: Configure the LLM(s) to use for applying controls
        #       Choose the appropriate model and provider based on needs/API keys
        #       It's crucial to set API keys as environment variables
        # Example using OpenAI (ensure OPENAI_API_KEY is set):
        self.llm_agent = Agent(
             model=OpenAIChat(id="gpt-4o-mini"), # Or another model like gpt-4o
             # model=Claude(id="claude-3-5-sonnet-latest"), # Or Anthropic (ensure ANTHROPIC_API_KEY)
             instructions=[
                 "You are a control verification assistant.",
                 "Execute the specific instruction provided for the control precisely.",
                 "Respond ONLY with the requested output format."
             ],
             markdown=False, # Adjust based on expected output format
             debug_mode=False # Set to True to see LLM interactions
         )
        # If different controls need different models/settings, you might initialize
        # multiple Agent instances or adjust settings per control.

    def run(self, extracted_text: str, prompt_files: list[str]) -> list[dict[str, Any]]:
        """
        Applies each control prompt to the extracted text using an LLM.
        Returns a list of dictionaries, each containing:
        {'id': control_id, 'description': description, 'instructions': instructions, 'result': result_text}
        """
        print(f"Controller: Applying {len(prompt_files)} controls...")
        detailed_results = [] # Changed from dict to list

        if not extracted_text:
            print("Controller: Error - Cannot apply controls, extracted text is empty.")
            # Return an empty list or potentially a list with a single error entry
            return []

        for prompt_file in prompt_files:
            control_id = os.path.basename(prompt_file) # Default ID
            description = "N/A"
            instructions = []
            result_content = "Error: Processing failed before LLM call."
            success_flag = False # Track if we should add this entry

            try:
                with open(prompt_file, 'r', encoding='utf-8') as f: # Specify encoding
                    control_data = json.load(f)

                control_id = control_data.get("control_id", control_id) # Use ID from file if present
                instructions = control_data.get("prompt_instructions", [])
                description = control_data.get("description", "N/A")

                if not instructions:
                    print(f"Controller: Warning - No 'prompt_instructions' found in {prompt_file}. Skipping.")
                    result_content = "Error: Prompt instructions missing."
                    # Decide if you want to include errors like this in the results list
                    # For grading, it might be useful to include them
                    # detailed_results.append({'id': control_id, 'description': description, 'instructions': instructions, 'result': result_content})
                    # continue # Or skip adding it
                else:
                    # Construct the prompt for the LLM
                    # Combine general instructions, specific control instructions, and the text
                    # Use a clear separator for the document text
                    # TODO: Refine prompt engineering for better results
                    # TODO: Handle large text (chunking might be needed before this agent or handled by Agno's context management)
                    full_prompt = (
                        f"Control Description: {description}\n"
                        f"Instructions:\n"
                        + "\n".join([f"- {inst}" for inst in instructions])
                        + "\n\n--- Document Text Start ---\n"
                        + extracted_text
                        + "\n--- Document Text End ---"
                    )

                    print(f"Controller: Applying control '{control_id}'...")
                    try:
                        # Use the Agno agent to get the response from the LLM
                        response = self.llm_agent.run(full_prompt, stream=False)

                        # --- Extract the content ---
                        if hasattr(response, 'content') and response.content is not None:
                            result_content = str(response.content) # Ensure string
                            success_flag = True # Mark as successful LLM call
                        elif response:
                            result_content = "Error: Empty Response from LLM agent."
                            print(f"Controller: Warning - LLM response for '{control_id}' has no content.")
                        else:
                            result_content = "Error: No response object from LLM agent."
                            print(f"Controller: Error - No response object from LLM agent for '{control_id}'.")

                        # Log a snippet of the actual result content
                        log_snippet = result_content[:100].replace('\n', ' ') + ("..." if len(result_content) > 100 else "")
                        print(f"Controller: Result for '{control_id}': {log_snippet}")

                    except Exception as llm_error:
                        print(f"Controller: Error applying control '{control_id}' via LLM: {llm_error}")
                        result_content = f"Error: LLM execution failed ({llm_error})"

            except FileNotFoundError:
                print(f"Controller: Error - Prompt file not found: {prompt_file}")
                result_content = "Error: Prompt file missing."
            except json.JSONDecodeError:
                print(f"Controller: Error - Invalid JSON in prompt file: {prompt_file}")
                result_content = "Error: Invalid JSON format."
            except Exception as e:
                print(f"Controller: Unexpected error processing {prompt_file}: {e}")
                result_content = f"Error: Unexpected ({e})"

            # Append the detailed result to the list
            # We append even if there were errors, as the grader might need to assign high risk scores
            detailed_results.append({
                'id': control_id,
                'description': description,
                'instructions': instructions, # Pass instructions for grader context
                'result': result_content
            })

        print("Controller: Finished applying controls.")
        return detailed_results
