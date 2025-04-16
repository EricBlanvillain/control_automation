import io
import contextlib
import os
import pathlib
import json # To parse/create prompt files
import time # <--- Add import for time.sleep
import logging # <-- Import logging
import shutil # <-- Import for file operations
import secrets # <-- Import for secure random filenames
import re # <-- IMPORT MISSING RE MODULE
from fastapi import FastAPI, HTTPException, Query, UploadFile, File # <-- Add UploadFile, File
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
# Directory for user uploads
UPLOADS_DIR = "uploads"

# Ensure uploads directory exists
pathlib.Path(UPLOADS_DIR).mkdir(parents=True, exist_ok=True)

# Configure API Log Level (from env or default to INFO)
API_LOG_LEVEL_STR = os.getenv('API_LOG_LEVEL', 'INFO').upper()
API_LOG_LEVEL = getattr(logging, API_LOG_LEVEL_STR, logging.INFO)

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

# New model for upload response
class UploadResponse(BaseModel):
    success: bool
    message: str
    file_path: Optional[str] = None # Path relative to backend root
    filename: Optional[str] = None

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

def sanitize_filename(filename: str) -> str:
    """Removes potentially dangerous characters from a filename."""
    # Remove path components
    filename = os.path.basename(filename)
    # Replace potentially problematic characters (simple example)
    # A more robust solution would use a whitelist of allowed characters.
    sanitized = re.sub(r'[^a-zA-Z0-9_.-]', '_', filename)
    # Limit length
    sanitized = sanitized[:100]
    if not sanitized:
        sanitized = "uploaded_file"
    print(f"[sanitize_filename] Original: '{filename}', Sanitized: '{sanitized}'")
    return sanitized

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

@app.post("/api/upload-document", response_model=UploadResponse)
async def upload_document(file: UploadFile = File(...)):
    """Accepts a document upload and saves it to the uploads directory."""
    if not file.filename:
        raise HTTPException(status_code=400, detail="No filename provided.")

    original_filename = file.filename
    print(f"API: Received upload request for file: {original_filename}")

    # Sanitize the filename to prevent security issues
    safe_filename = sanitize_filename(original_filename)
    # Optional: Generate a unique filename to avoid conflicts/overwrites
    # unique_suffix = secrets.token_hex(4)
    # file_extension = pathlib.Path(safe_filename).suffix
    # unique_filename = f"{pathlib.Path(safe_filename).stem}_{unique_suffix}{file_extension}"
    # For simplicity, we'll use the sanitized name for now, but overwrites are possible.
    save_path = pathlib.Path(UPLOADS_DIR) / safe_filename

    try:
        print(f"API: Saving uploaded file to: {save_path}")
        # Read the file content asynchronously and write to the target path
        with open(save_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        # Return the relative path to the saved file
        relative_path = str(save_path)
        print(f"API: File uploaded successfully to {relative_path}")
        return UploadResponse(
            success=True,
            message="File uploaded successfully.",
            file_path=relative_path, # Path relative to backend root
            filename=safe_filename
        )
    except Exception as e:
        print(f"API Error: Failed to save uploaded file {safe_filename}: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Failed to save uploaded file. Error: {e}")
    finally:
        # Ensure the file descriptor is closed
        await file.close()

@app.post("/api/run-controls", response_model=ControlResponse)
def run_controls_endpoint(request: ControlRequest):
    # --- Security Check: Target Path --- #
    # The target path could now be in TARGET_BASE_DIR or UPLOADS_DIR
    print(f"API: Checking safety of target path: {request.target_path}")
    if not (is_safe_path(TARGET_BASE_DIR, request.target_path) or is_safe_path(UPLOADS_DIR, request.target_path)):
         print(f"API Security Alert: Attempt to access target outside allowed directories: {request.target_path}")
         # Check if it simply doesn't exist yet
         if not pathlib.Path(request.target_path).exists():
              raise HTTPException(status_code=404, detail=f"Target path not found: {request.target_path}")
         else:
              raise HTTPException(status_code=403, detail="Access denied: Target path is invalid or outside allowed directories.")
    # ------------------------------------ #

    print(f"API: Received run request for target: {request.target_path}, Category: {request.category or 'Auto'}")
    orchestrator = OrchestratorAgent()
    detailed_results_with_scores: Optional[List[Dict[str, Any]]] = None
    final_report_path: Optional[str] = None
    api_logs = [] # Start with API-level logs

    # --- Set up logging capture --- #
    log_stream = io.StringIO()
    root_logger = logging.getLogger()
    log_formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    stream_handler = logging.StreamHandler(log_stream)
    stream_handler.setFormatter(log_formatter)
    stream_handler.setLevel(API_LOG_LEVEL)
    original_level = root_logger.level
    if root_logger.level > API_LOG_LEVEL:
         root_logger.setLevel(API_LOG_LEVEL)
    root_logger.addHandler(stream_handler)
    api_logs.append(f"API: Log capture initialized at level {logging.getLevelName(API_LOG_LEVEL)}.")
    # ------------------------------ #

    try:
        # --- Run the Orchestrator --- #
        detailed_results_with_scores, final_report_path = orchestrator.run_control_chain(
            document_path=request.target_path,
            specified_meta_category=request.category
        )
        # ------------------------------ #
        api_logs.append("API: Orchestrator chain finished.")
        # --- Determine Success (checks if detailed_results_with_scores is not None) ---
        if final_report_path and detailed_results_with_scores is not None:
            success = True
            message = "Control chain executed successfully."
            print(f"API: Process finished. Orchestrator returned results and report path: {final_report_path}")
        elif final_report_path and detailed_results_with_scores is None:
             success = False
             message = "Control chain failed during execution, but a failure report was generated."
             print(f"API: Process failed (no results). Orchestrator returned failure report path: {final_report_path}")
        elif not final_report_path and detailed_results_with_scores is not None:
             success = True
             message = "Control chain finished (results generated), but failed to get report path."
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
        report_to_return = final_report_path # Use the path returned by the orchestrator
        if report_to_return:
            print(f"API: Using report path provided by orchestrator: {report_to_return}")
        else:
            print("API Warning: No report path received from orchestrator.")
            if success:
                message += " (Report path unavailable)"
            else:
                 message += " (No report generated)"

        # Add final status to API logs
        api_logs.append(f"API: Processing complete. {message}")

        # --- Retrieve captured logs --- #
        captured_logs = log_stream.getvalue().splitlines()
        # ---------------------------- #

        return ControlResponse(
            success=success,
            message=message,
            report_path=report_to_return,
            logs=api_logs + captured_logs, # Combine API logs and captured agent logs
            summary=summary_line
        )

    except FileNotFoundError as e:
        print(f"API Error: File not found - {e}")
        api_logs.append(f"API ERROR: File not found - {e}") # Log error
        raise HTTPException(status_code=404, detail=f"Target path not found: {request.target_path}")
    except Exception as e:
        print(f"API Error: Failed to run control chain - {e}")
        traceback.print_exc() # Print full traceback to server console
        api_logs.append(f"API ERROR: Orchestration failed - {e}") # Log error
        # Return captured logs even if an error occurred during execution
        captured_logs = log_stream.getvalue().splitlines()
        error_message = f"Failed to run control chain: {e}"
        return ControlResponse(
            success=False,
            message=error_message,
            report_path=None,
            logs=api_logs + captured_logs + [f"ERROR: {error_message}"], # Add error to combined logs
            summary=None
        )
    finally:
        # --- Clean up log handler --- #
        root_logger.removeHandler(stream_handler)
        # Restore original root logger level if we changed it
        root_logger.setLevel(original_level)
        log_stream.close()
        print("API: Log handler removed.")
        # ---------------------------- #

@app.get("/api/prompt-details", response_model=FullPromptData)
def get_prompt_details(file_path: str = Query(..., description="Relative path to the prompt JSON file")):
    """Gets the full content of a specific prompt JSON file."""
    print(f"API: Request for details for prompt: {file_path}")
    if not is_safe_path(PROMPTS_DIR, file_path):
        print(f"API Security Alert: Attempt to access prompt outside PROMPTS_DIR: {file_path}")
        raise HTTPException(status_code=403, detail="Access denied: Prompt path is invalid or outside allowed directory.")
    try:
        prompt_path_obj = pathlib.Path(file_path)
        if not prompt_path_obj.is_file():
             raise FileNotFoundError(f"Prompt file not found at expected path: {file_path}")
        with open(prompt_path_obj, 'r', encoding='utf-8') as f:
            data = json.load(f)
        required = ["control_id", "description", "meta_category", "prompt_instructions", "expected_output_format"]
        if not all(key in data for key in required):
             print(f"API Error: Prompt file {file_path} is missing required fields.")
             raise ValueError("Prompt file is missing required fields.")
        if not isinstance(data["prompt_instructions"], list):
            raise ValueError("prompt_instructions must be a list.")
        full_data = FullPromptData(
            control_id=data["control_id"],
            description=data["description"],
            meta_category=data["meta_category"],
            prompt_instructions=data["prompt_instructions"],
            expected_output_format=data["expected_output_format"],
            file_path=file_path
        )
        return full_data
    except FileNotFoundError as e:
         print(f"API Error: Prompt details - File not found: {e}")
         raise HTTPException(status_code=404, detail=str(e))
    except (json.JSONDecodeError, ValueError) as e:
         print(f"API Error: Prompt details - Invalid format: {e}")
         raise HTTPException(status_code=422, detail=f"Invalid prompt file format: {e}")
    except Exception as e:
        print(f"API Error: Failed to get prompt details for {file_path}: {e}")
        raise HTTPException(status_code=500, detail="Failed to load prompt details.")

@app.put("/api/update-prompt")
def update_prompt(update_data: UpdatePromptRequest):
    """Updates an existing control prompt JSON file. Handles category changes (file move)."""
    original_file_path_str = update_data.file_path
    print(f"API: Request to update prompt file: {original_file_path_str}")

    # Security Check: Ensure the original path is within the PROMPTS_DIR
    if not is_safe_path(PROMPTS_DIR, original_file_path_str):
        print(f"API Security Alert: Attempt to update prompt outside PROMPTS_DIR: {original_file_path_str}")
        raise HTTPException(status_code=403, detail="Access denied: Original path is invalid or outside allowed directory.")

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

@app.delete("/api/delete-prompt")
def delete_prompt(file_path: str = Query(..., description="Relative path to the prompt JSON file to delete")):
    """Deletes an existing control prompt JSON file."""
    print(f"API: Request to delete prompt file: {file_path}")
    if not is_safe_path(PROMPTS_DIR, file_path):
        print(f"API Security Alert: Attempt to delete prompt outside PROMPTS_DIR: {file_path}")
        raise HTTPException(status_code=403, detail="Access denied: Path is invalid or outside allowed directory.")
    try:
        prompt_path_obj = pathlib.Path(file_path)
        if not prompt_path_obj.is_file():
             raise FileNotFoundError(f"Prompt file not found: {file_path}")
        prompt_path_obj.unlink()
        print(f"API: Successfully deleted prompt file: {file_path}")
        return {"message": "Prompt deleted successfully", "deleted_file_path": file_path}
    except FileNotFoundError as e:
         print(f"API Error: Delete prompt - File not found: {e}")
         raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        print(f"API Error: Failed to delete prompt {file_path}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to delete prompt file. {e}")

# --- Run the server (for local development) ---
if __name__ == "__main__":
    import uvicorn
    host = os.getenv("HOST", "127.0.0.1")
    port = int(os.getenv("PORT", 8000))
    # Setup basic logging for the server itself (will be overridden by orchestrator setup if run from here)
    logging.basicConfig(level=logging.INFO, format='%(levelname)s:     %(message)s')
    print(f"Starting Control Automation API server on {host}:{port}")
    uvicorn.run("api_server:app", host=host, port=port, reload=True)
