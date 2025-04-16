import io
import contextlib
import os
import pathlib
import json # To parse/create prompt files
import time # <--- Add import for time.sleep
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse, JSONResponse
from pydantic import BaseModel, Field # For validation
from typing import Optional, List, Dict, Any
from datetime import datetime

# Load environment variables (from .env file)
from dotenv import load_dotenv
load_dotenv()

# Import your orchestrator agent
from agents.orchestrator import OrchestratorAgent, KNOWN_META_CATEGORIES
from agno.agent import Agent # Need Agent class
from agno.models.openai import OpenAIChat # Or other models if needed
from agno.models.anthropic import Claude
import traceback # For detailed error logging

# --- Configuration ---
# Base directory from which the frontend can select targets
TARGET_BASE_DIR = "test_documents"
# Directory where reports are stored
REPORTS_DIR = "reports"
PROMPTS_DIR = "prompts"

# --- Pydantic Models for Request/Response ---
class ControlRequest(BaseModel):
    target_path: str
    # Category is optional, backend will infer if not provided
    category: Optional[str] = None

class ControlResponse(BaseModel):
    success: bool
    message: str
    report_path: Optional[str] = None
    logs: Optional[List[str]] = None
    summary: Optional[str] = None

class TargetListResponse(BaseModel):
    targets: List[str]

class PromptDetail(BaseModel):
    id: str
    description: str
    file_path: str

class PromptListResponse(BaseModel):
    prompts_by_category: Dict[str, List[PromptDetail]]

class CreatePromptRequest(BaseModel):
    control_id: str = Field(..., pattern=r"^[A-Z0-9_]+$") # Basic validation: uppercase, numbers, underscore
    description: str
    meta_category: str
    prompt_instructions: List[str] = Field(..., min_length=1) # Must have at least one instruction
    expected_output_format: str

# --- Pydantic model for getting full prompt details ---
class FullPromptData(CreatePromptRequest): # Inherits fields from create request
    file_path: str # Add file path to the response

# --- Pydantic model for updating a prompt ---
class UpdatePromptRequest(BaseModel):
    file_path: str # Identify the file to update
    # Include all editable fields
    description: str
    meta_category: str # Allowing category change means moving the file
    prompt_instructions: List[str] = Field(..., min_length=1)
    expected_output_format: str
    # Note: control_id is derived from file_path usually, or part of path param

# --- FastAPI App Initialization ---
app = FastAPI(
    title="Control Automation API",
    description="API to trigger document control automation process and manage prompts.",
    version="0.1.0"
)

# --- CORS Configuration ---
# Allow requests from the default Vite dev server origin
origins = [
    "http://localhost:5173", # Default Vite port
    "http://127.0.0.1:5173",
    # Add other origins if needed (e.g., your deployed frontend URL)
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"], # Allow all methods (GET, POST, etc.)
    allow_headers=["*"], # Allow all headers
)

# --- Helper Functions ---
def is_safe_path(base_dir: str, requested_path_str: str) -> bool:
    """Check if the requested path is safely within the base directory."""
    print(f"[is_safe_path] Checking base='{base_dir}', requested='{requested_path_str}'")
    try:
        # Resolve both paths to absolute paths
        base_path = pathlib.Path(base_dir).resolve(strict=True)
        print(f"[is_safe_path] Resolved base_path: {base_path}")
        requested_path = pathlib.Path(requested_path_str).resolve(strict=True)
        print(f"[is_safe_path] Resolved requested_path: {requested_path}")

        # Check if the requested path is equal to or a subpath of the base path
        is_relative = requested_path.is_relative_to(base_path)
        print(f"[is_safe_path] Is relative: {is_relative}")
        return is_relative
    except FileNotFoundError as e:
        print(f"[is_safe_path] FileNotFoundError during resolve: {e}")
        return False
    except Exception as e:
        print(f"[is_safe_path] Exception during check: {e}")
        return False

# --- API Endpoints ---
@app.get("/")
def read_root():
    """Root endpoint for basic API health check."""
    return {"message": "Control Automation API is running."}

@app.get("/api/list-targets", response_model=TargetListResponse)
def list_targets():
    """Lists *files* recursively within the configured TARGET_BASE_DIR."""
    targets = []
    base_path = pathlib.Path(TARGET_BASE_DIR)

    if not base_path.is_dir():
        print(f"API Error: TARGET_BASE_DIR '{TARGET_BASE_DIR}' not found or is not a directory.")
        # Return empty list or raise an error, returning empty for now
        return TargetListResponse(targets=[])

    try:
        # Use rglob to find all items, then filter for files
        for item in base_path.rglob('*'):
            # Skip directories, hidden files/dirs, cache dirs
            if not item.is_file() or "__pycache__" in item.parts or item.name.startswith('.'):
                continue

            # We want to return paths relative to the project root
            # or at least relative to the TARGET_BASE_DIR for clarity
            relative_path = str(item) # Path relative to project root
            targets.append(relative_path)

        # Sort for consistent order
        targets.sort()
        print(f"API: Found {len(targets)} target files in '{TARGET_BASE_DIR}'")
        return TargetListResponse(targets=targets)

    except Exception as e:
        print(f"API Error: Failed to list targets in '{TARGET_BASE_DIR}': {e}")
        raise HTTPException(status_code=500, detail="Failed to list available targets.")

@app.get("/api/list-prompts", response_model=PromptListResponse)
def list_prompts():
    """Lists existing control prompts, parsing details from JSON files."""
    prompts_by_category: Dict[str, List[PromptDetail]] = {}
    base_path = pathlib.Path(PROMPTS_DIR)

    if not base_path.is_dir():
        print(f"API Error: PROMPTS_DIR '{PROMPTS_DIR}' not found.")
        return PromptListResponse(prompts_by_category={})

    try:
        # Iterate through category directories
        for category_dir in base_path.iterdir():
            if category_dir.is_dir() and not category_dir.name.startswith('.'):
                category_name = category_dir.name
                prompts_by_category[category_name] = []
                # Iterate through JSON files in the category directory
                for prompt_file in category_dir.glob('*.json'):
                    try:
                        with open(prompt_file, 'r', encoding='utf-8') as f:
                            data = json.load(f)
                        # Extract details (provide defaults if keys are missing)
                        prompt_detail = PromptDetail(
                            id=data.get("control_id", prompt_file.stem), # Use filename stem if id missing
                            description=data.get("description", "(No description)"),
                            file_path=str(prompt_file) # Path relative to project root
                        )
                        prompts_by_category[category_name].append(prompt_detail)
                    except json.JSONDecodeError:
                        print(f"API Warning: Skipping invalid JSON file: {prompt_file}")
                    except Exception as file_e:
                        print(f"API Warning: Error reading prompt file {prompt_file}: {file_e}")
                # Sort prompts within category by ID
                prompts_by_category[category_name].sort(key=lambda p: p.id)

        print(f"API: Found prompts in {len(prompts_by_category)} categories.")
        return PromptListResponse(prompts_by_category=prompts_by_category)

    except Exception as e:
        print(f"API Error: Failed to list prompts in '{PROMPTS_DIR}': {e}")
        raise HTTPException(status_code=500, detail="Failed to list available prompts.")

@app.post("/api/create-prompt", status_code=201)
def create_prompt(prompt_data: CreatePromptRequest):
    """Creates a new control prompt JSON file."""
    print(f"API: Received request to create prompt: ID={prompt_data.control_id}, Category={prompt_data.meta_category}")
    base_path = pathlib.Path(PROMPTS_DIR)
    category_path = base_path / prompt_data.meta_category
    file_name = f"{prompt_data.control_id}.json"
    file_path = category_path / file_name

    # Validate category (optional, could allow creating new ones)
    if prompt_data.meta_category not in KNOWN_META_CATEGORIES:
        print(f"API Warning: Attempt to create prompt in unknown category '{prompt_data.meta_category}'. Allowing for now.")
        # Or raise HTTPException(status_code=400, detail="Invalid meta_category.")

    # Create category directory if it doesn't exist
    try:
        category_path.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        print(f"API Error: Could not create directory {category_path}: {e}")
        raise HTTPException(status_code=500, detail="Failed to create category directory.")

    # Check if file already exists
    if file_path.exists():
        print(f"API Error: Prompt file already exists: {file_path}")
        raise HTTPException(status_code=409, detail=f"Prompt with ID '{prompt_data.control_id}' already exists in category '{prompt_data.meta_category}'.")

    # Prepare JSON content
    json_content = {
        "control_id": prompt_data.control_id,
        "description": prompt_data.description,
        "meta_category": prompt_data.meta_category,
        "prompt_instructions": prompt_data.prompt_instructions,
        "expected_output_format": prompt_data.expected_output_format
    }

    # Write JSON file
    try:
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(json_content, f, indent=2) # Use indent for readability
        print(f"API: Successfully created prompt file: {file_path}")
        return {"message": "Prompt created successfully", "file_path": str(file_path)}
    except Exception as e:
        print(f"API Error: Failed to write prompt file {file_path}: {e}")
        raise HTTPException(status_code=500, detail="Failed to save prompt file.")

@app.get("/api/get-report-content", response_class=PlainTextResponse)
def get_report_content(report_path: str = Query(..., description="Relative path to the report file")):
    """Gets the content of a specific report file."""
    print(f"API: Received request for report content: {report_path}")

    # Security Check: Ensure the requested path is within the REPORTS_DIR
    if not is_safe_path(REPORTS_DIR, report_path):
        print(f"API Security Alert: Attempt to access report outside REPORTS_DIR: {report_path}")
        raise HTTPException(status_code=403, detail="Access denied: Report path is invalid or outside allowed directory.")

    try:
        # is_safe_path already confirmed the file exists via resolve(strict=True)
        file_path = pathlib.Path(report_path)
        content = file_path.read_text(encoding="utf-8")
        print(f"API: Successfully read report content from {report_path}")
        return PlainTextResponse(content=content)
    except FileNotFoundError:
        # This should technically be caught by is_safe_path, but handle defensively
        print(f"API Error: Report file not found at {report_path}")
        raise HTTPException(status_code=404, detail="Report file not found.")
    except Exception as e:
        print(f"API Error: Failed to read report file {report_path}: {e}")
        raise HTTPException(status_code=500, detail="Failed to read report file.")

@app.post("/api/run-controls", response_model=ControlResponse)
def run_controls_endpoint(request: ControlRequest):
    print(f"API: Received run request for target: {request.target_path}, Category: {request.category or 'Auto'}")
    orchestrator = OrchestratorAgent()
    log_capture = io.StringIO()
    # Expects detailed results WITH scores now
    detailed_results_with_scores: Optional[List[Dict[str, Any]]] = None
    final_report_path: Optional[str] = None

    try:
        with contextlib.redirect_stdout(log_capture):
            # Capture DETAILED_RESULTS_WITH_SCORES and REPORT_PATH directly
            detailed_results_with_scores, final_report_path = orchestrator.run_control_chain(
                document_path=request.target_path,
                specified_meta_category=request.category
            )

        log_output = log_capture.getvalue().splitlines()

        # --- Determine Success (checks if detailed_results_with_scores is not None) ---
        if final_report_path and detailed_results_with_scores is not None:
            success = True
            message = "Control chain executed successfully."
            print(f"API: Process finished. Orchestrator returned results (with scores) and report path: {final_report_path}")
        elif final_report_path and detailed_results_with_scores is None:
             success = False
             message = "Control chain failed during execution, but a failure report was generated."
             print(f"API: Process failed (no results). Orchestrator returned failure report path: {final_report_path}")
        elif not final_report_path and detailed_results_with_scores is not None:
             success = True
             message = "Control chain finished (results generated), but failed to get report path from orchestrator."
             print("API Warning: Orchestrator returned results but no report path.")
        else:
            success = False
            message = "Control chain failed to produce results or a report."
            print("API Error: Orchestrator returned no results and no report path.")

        # --- Calculate Summary using Scores from Orchestrator (Synthesized Logic) ---
        total_controls = 0
        passed_controls = 0
        summary_line = "Tests Passed: N/A"

        if detailed_results_with_scores:
            # Group results by control ID
            results_by_id: Dict[str, List[Dict[str, Any]]] = {}
            for item in detailed_results_with_scores:
                control_id = item.get('id', 'UnknownID')
                if control_id not in results_by_id:
                    results_by_id[control_id] = []
                results_by_id[control_id].append(item)

            total_controls = len(results_by_id) # Total unique controls
            print(f"API: Calculating summary for {total_controls} unique controls...")

            # Determine pass/fail for each unique control
            for control_id, items in results_by_id.items():
                # Find the MINIMUM valid score achieved for this control across all chunks
                # Treat scores <= 0 (like -1 for grading errors) as max risk (10) when finding min
                valid_scores = [item.get('score', 10) for item in items if isinstance(item.get('score'), int)]
                scores_for_min = [s if s > 0 else 10 for s in valid_scores]
                min_score = min(scores_for_min) if scores_for_min else 10 # Default to 10 (fail) if no valid scores

                # Find the Maximum score as well, for reporting purposes (though report logic also does this)
                scores_for_max = [s if s > 0 else 10 for s in valid_scores]
                max_score = max(scores_for_max) if scores_for_max else 10

                print(f"API Summary: Control={control_id}, Min Score={min_score}, Max Score={max_score}")

                # Apply threshold TO MIN SCORE: Pass if the BEST score achieved was < 5
                if 1 <= min_score < 5:
                    passed_controls += 1
                    print(f"API Summary: Control {control_id} PASSED (based on min score)")
                else:
                    print(f"API Summary: Control {control_id} FAILED (based on min score)")

            summary_line = f"Tests Passed: {passed_controls} out of {total_controls}"
            print(f"API Summary: Final count -> Passed: {passed_controls}/{total_controls} unique controls")
        else:
             print("API Warning: No scored results returned from orchestrator to calculate summary.")
             summary_line = "Tests Passed: 0 out of 0"

        # --- Report Handling ---
        report_to_return = None

        # Use the directly returned final_report_path
        # Modify report only if controls actually ran (detailed_results is not None)
        if final_report_path and detailed_results_with_scores is not None:
            try:
                report_path_obj = pathlib.Path(final_report_path)
                time.sleep(0.1) # Keep the small delay
                is_file = report_path_obj.is_file()
                if is_file:
                     original_content = report_path_obj.read_text(encoding="utf-8")
                     # ... (insertion point calculation) ...
                     insertion_point = -1
                     report_gen_marker = "Report Generated:"
                     report_gen_line_pos = original_content.find(report_gen_marker)
                     if report_gen_line_pos != -1:
                          end_of_line_pos = original_content.find("\n", report_gen_line_pos)
                          if end_of_line_pos != -1:
                               insertion_point = end_of_line_pos + 1
                          else:
                               insertion_point = len(original_content)
                     else:
                          header_end_marker = "--- Control Automation Report ---"
                          header_pos = original_content.find(header_end_marker)
                          if header_pos != -1:
                               double_newline_pos = original_content.find("\n\n", header_pos)
                               if double_newline_pos != -1:
                                    insertion_point = double_newline_pos + 2
                     if insertion_point == -1:
                          insertion_point = 0
                     # ... (end insertion point calculation) ...
                     summary_section = f"\n--- Summary ---\n{summary_line}\n"
                     modified_content = original_content[:insertion_point] + summary_section + original_content[insertion_point:]
                     report_path_obj.write_text(modified_content, encoding="utf-8")
                     report_to_return = final_report_path
                     log_output.append(f"Summary added to report: {final_report_path}")
                else:
                     print(f"API Warning: Report path '{final_report_path}' received, but file not found. Creating new report.")
            except Exception as e:
                print(f"API Error: Failed to read/modify existing report '{final_report_path}': {e}. Creating new report.")

        # --- Fallback Report Creation ---
        # Modify fallback to use detailed_results_with_scores for content AND consolidate
        if not report_to_return and success:
             print("API: Creating new consolidated report file with summary (fallback).")
             new_report_filename = f"report_{datetime.now().strftime('%Y%m%d%H%M%S')}.txt"
             new_report_path = pathlib.Path(REPORTS_DIR) / new_report_filename
             new_report_path.parent.mkdir(parents=True, exist_ok=True)
             try:
                 with open(new_report_path, "w", encoding="utf-8", newline='\n') as f:
                     f.write("--- Control Automation Report ---\n\n")
                     f.write(f"Original Document: {request.target_path}\n")
                     f.write(f"Report Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                     f.write("\n--- Summary ---\n")
                     f.write(f"{summary_line}\n") # Add summary
                     f.write("\n--- Control Results (Consolidated) ---\n\n") # Updated title

                     if not detailed_results_with_scores:
                         f.write("No control results were generated.\n")
                     else:
                        # Group results by control ID to consolidate
                        results_by_id: Dict[str, List[Dict[str, Any]]] = {}
                        for item in detailed_results_with_scores:
                            control_id = item.get('id', 'UnknownID')
                            if control_id not in results_by_id:
                                results_by_id[control_id] = []
                            results_by_id[control_id].append(item)

                        # Process each unique control ID
                        for control_id, items in sorted(results_by_id.items()):
                            # Find the item with the MAXIMUM valid score (>= 1)
                            worst_item = None
                            max_score = -1
                            for item in items:
                                score = item.get('score', -1)
                                if isinstance(score, (int, float)):
                                    current_score_for_max = score if score > 0 else 10
                                    if current_score_for_max >= max_score:
                                        if current_score_for_max > max_score or worst_item is None:
                                            max_score = current_score_for_max
                                            worst_item = item
                                elif worst_item is None:
                                     worst_item = item

                            if worst_item is None and items:
                                 worst_item = items[0]
                                 max_score = worst_item.get('score', 'N/A')
                            elif max_score == -1:
                                 max_score = worst_item.get('score', 'N/A') if worst_item else 'N/A'
                            elif max_score == 10 and worst_item and worst_item.get('score', 10) <= 0:
                                 max_score = worst_item.get('score', 'Error')

                            if worst_item:
                                result_str = str(worst_item.get('result', ''))
                                # Write the consolidated entry using the highest risk score
                                f.write(f"Control ID: {control_id} (Global Risk Score: {max_score}/10)\n")
                                f.write(f"Result: {result_str}\n")
                                f.write("-" * 20 + "\n")

                     f.write("\n--- End of Report ---\n")
                 report_to_return = str(new_report_path)
                 print(f"API: New report generated successfully at {report_to_return}")
             except Exception as e:
                  print(f"API Error: Failed to write new consolidated report: {e}")
                  success = False
                  message = f"Control chain finished, but failed to generate report. Error: {e}"
        elif not report_to_return and not success and final_report_path:
             report_to_return = final_report_path
             print(f"API: Returning path to failure report: {report_to_return}")

        # Add final status to logs
        log_output.append(f"Processing complete. {message}")

        return ControlResponse(
            success=success,
            message=message,
            report_path=report_to_return, # Use the determined path
            logs=log_output,
            summary=summary_line # <-- Include summary_line in the response
        )

    except FileNotFoundError as e:
        print(f"API Error: File not found - {e}")
        raise HTTPException(status_code=404, detail=f"Target path not found: {request.target_path}")
    except Exception as e:
        print(f"API Error: Failed to run control chain - {e}")
        # Capture logs even if an error occurred during execution
        log_output = log_capture.getvalue().splitlines()
        # Include error details in the message
        error_message = f"Failed to run control chain: {e}"
        # Return logs and error message
        return ControlResponse(
            success=False,
            message=error_message,
            report_path=None,
            logs=log_output + [f"ERROR: {error_message}"], # Add error to logs
            summary=None # <-- Include None for summary field
        )
        # Alternatively, raise HTTPException for internal errors:
        # raise HTTPException(status_code=500, detail=f"Internal server error: {e}")

@app.get("/api/prompt-details", response_model=FullPromptData)
def get_prompt_details(file_path: str = Query(..., description="Relative path to the prompt JSON file")):
    """Gets the full content of a specific prompt JSON file."""
    print(f"API: Received request for prompt details: {file_path}")

    # Security Check: Ensure the requested path is within the PROMPTS_DIR
    if not is_safe_path(PROMPTS_DIR, file_path):
        print(f"API Security Alert: Attempt to access prompt outside PROMPTS_DIR: {file_path}")
        raise HTTPException(status_code=403, detail="Access denied: Prompt path is invalid or outside allowed directory.")

    try:
        path_obj = pathlib.Path(file_path)
        if not path_obj.is_file():
             raise HTTPException(status_code=404, detail="Prompt file not found.")

        with open(path_obj, 'r', encoding='utf-8') as f:
            data = json.load(f)

        # Populate the response model
        full_data = FullPromptData(
            control_id=data.get("control_id", path_obj.stem), # Use ID from file or filename stem
            description=data.get("description", ""),
            meta_category=data.get("meta_category", path_obj.parent.name), # Infer category from parent dir
            prompt_instructions=data.get("prompt_instructions", []),
            expected_output_format=data.get("expected_output_format", ""),
            file_path=str(file_path) # Include the original file path
        )
        print(f"API: Successfully read prompt details from {file_path}")
        return full_data
    except json.JSONDecodeError:
         print(f"API Error: Invalid JSON in prompt file {file_path}")
         raise HTTPException(status_code=500, detail="Failed to parse prompt file (invalid JSON).")
    except FileNotFoundError:
         # Should be caught by is_safe_path or the explicit check, but handle defensively
        print(f"API Error: Prompt file not found at {file_path}")
        raise HTTPException(status_code=404, detail="Prompt file not found.")
    except Exception as e:
        print(f"API Error: Failed to read prompt details from {file_path}: {e}")
        raise HTTPException(status_code=500, detail="Failed to read prompt file.")

@app.put("/api/update-prompt")
def update_prompt(update_data: UpdatePromptRequest):
    """Updates an existing control prompt JSON file. Handles category changes (file move)."""
    original_file_path_str = update_data.file_path
    print(f"API: Received request to update prompt: {original_file_path_str}")

    # Security Check: Ensure the original path is within the PROMPTS_DIR
    if not is_safe_path(PROMPTS_DIR, original_file_path_str):
        print(f"API Security Alert: Attempt to update prompt outside PROMPTS_DIR: {original_file_path_str}")
        raise HTTPException(status_code=403, detail="Access denied: Original path is invalid.")

    original_path_obj = pathlib.Path(original_file_path_str)
    if not original_path_obj.is_file():
        raise HTTPException(status_code=404, detail=f"Original prompt file not found: {original_file_path_str}")

    # Determine the new path based on potential category change
    original_control_id = original_path_obj.stem
    new_category = update_data.meta_category
    new_category_path = pathlib.Path(PROMPTS_DIR) / new_category
    new_file_path = new_category_path / f"{original_control_id}.json" # Keep original ID/filename stem

    # Security Check: Ensure the new category path is also within PROMPTS_DIR (redundant but safe)
    if not is_safe_path(PROMPTS_DIR, str(new_file_path)):
         print(f"API Security Alert: Attempt to move prompt outside PROMPTS_DIR: {new_file_path}")
         raise HTTPException(status_code=400, detail="Invalid target category path.")

    # Prepare new JSON content (using original ID)
    json_content = {
        "control_id": original_control_id,
        "description": update_data.description,
        "meta_category": new_category,
        "prompt_instructions": update_data.prompt_instructions,
        "expected_output_format": update_data.expected_output_format
    }

    try:
        # Create new category directory if needed
        new_category_path.mkdir(parents=True, exist_ok=True)

        # Write the new content to the target path (overwrite if it exists)
        with open(new_file_path, 'w', encoding='utf-8') as f:
            json.dump(json_content, f, indent=2)
        print(f"API: Successfully wrote updated prompt to: {new_file_path}")

        # If the path changed (category changed), delete the old file
        if original_path_obj != new_file_path:
            try:
                original_path_obj.unlink()
                print(f"API: Successfully deleted old prompt file at: {original_path_obj}")
            except OSError as unlink_error:
                 print(f"API Warning: Failed to delete old prompt file {original_path_obj}: {unlink_error}. New file was created.")
                 # Proceed, but maybe log this more prominently

        return {"message": "Prompt updated successfully", "new_file_path": str(new_file_path)}

    except Exception as e:
        print(f"API Error: Failed to update prompt file {original_file_path_str} -> {new_file_path}: {e}")
        # Attempt to clean up if write failed but old file was deleted? Unlikely path change scenario.
# --- How to Run ---
# Activate your .venv: source .venv/bin/activate
# Run the server: uvicorn api_server:app --reload
# The API will be available at http://127.0.0.1:8000
