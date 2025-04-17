# Control Automation Project

This project uses a multi-agent system built with [Agno](https://docs.agno.com/) and a FastAPI/React web interface to automate control checks on various documents (Word, Excel, PDF).

## Overview

The system allows users to select documents via a web UI and trigger a control chain. The backend orchestrates several agents:

1.  **Orchestrator:** Determines the relevant control meta-category (e.g., KYC, RGPD, LCBFT) based on the document's path or user input. Coordinates the workflow.
2.  **Extractor:** Extracts text content from the document (supports DOCX, XLSX, TXT). Uses the Mistral OCR API for PDF documents, handling complex layouts and mixed content, returning Markdown.
3.  **Selector:** Selects appropriate control prompts (defined in JSON files) based on the meta-category.
4.  **Controller:** Applies each selected control prompt to the *most relevant* text chunks (retrieved via vector search using OpenAI embeddings) using a configured LLM.
5.  **Grader (New):** Evaluates the result of *each* control using an LLM, assigning a risk score from 1 (low risk/pass) to 10 (high risk/fail).
6.  **Reporter:** Generates a final report file summarizing the results. This report now includes a `--- Summary ---` section indicating the number of controls passed based on the Grader's scores (score < 5 = Pass), and includes chunk details for the highest-risk result.

## Project Structure

```
control_automation/
├── backend/                  # Contains backend FastAPI server and agent logic
│   ├── agents/               # Agent implementations (Orchestrator, Extractor, Selector, Controller, Grader, Reporter)
│   │   ├── __init__.py
│   │   ├── orchestrator.py
│   │   ├── ... (other agents)
│   │   └── grader.py         # New Grader agent
│   ├── prompts/              # Control prompts (JSON files by category)
│   │   ├── KYC/
│   │   └── ...
│   ├── reports/              # Generated control reports
│   ├── test_documents/       # Example documents for testing
│   │   ├── KYC/
│   │   └── ...
│   ├── api_server.py         # FastAPI application
│   └── ... (other backend files)
├── frontend/                 # Contains React frontend application
│   ├── public/
│   ├── src/
│   │   ├── App.tsx           # Main application component
│   │   └── ...
│   ├── package.json
│   └── ... (other frontend files)
├── .env.example            # Example environment variables file
├── .gitignore
├── requirements.txt        # Python dependencies for backend
├── start_backend.sh        # Script to start the backend server
├── start_frontend.sh       # Script to start the frontend dev server
└── README.md               # This file
```

## Setup

1.  **Clone the repository:**
    ```bash
    git clone <your-repo-url>
    cd control_automation
    ```

2.  **Backend Setup:**
    *   **Create and activate Python environment:**
        ```bash
        # Using venv
        python -m venv venv
        source venv/bin/activate  # On Windows use `venv\Scripts\activate`

        # Or using uv (if installed)
        # uv venv
        # source .venv/bin/activate
        ```
    *   **Install Python dependencies:**
        ```bash
        pip install -r requirements.txt
        # Or using uv
        # uv pip install -r requirements.txt
        ```
        *Note: The Tesseract OCR engine is **no longer required** locally as PDF processing now uses the Mistral API.*
    *   **Configure API Keys:** Create a `.env` file in the `control_automation/` root directory (copy from `.env.example`). Set the API keys for your chosen services:
        ```dotenv
        # .env
        OPENAI_API_KEY="sk-..."      # Required for text embeddings (Extractor/Controller)
        MISTRAL_API_KEY="sk-..."     # Required for PDF OCR (Extractor)
        # ANTHROPIC_API_KEY="sk-..." # If using Anthropic models (Controller/Grader)
        ```

3.  **Frontend Setup:**
    *   **Navigate to frontend directory:**
        ```bash
        cd frontend
        ```
    *   **Install Node.js dependencies:**
        ```bash
        npm install
        # Or using yarn: yarn install
        ```
    *   **Return to project root:**
        ```bash
        cd ..
        ```

## Running the Application

You need to run both the backend server and the frontend development server.

1.  **Start the Backend (from project root `control_automation/`):**
    ```bash
    ./start_backend.sh
    ```
    This will activate the virtual environment and start the FastAPI server (usually at `http://127.0.0.1:8000`).

2.  **Start the Frontend (from project root `control_automation/`):**
    Open a *new terminal* in the `control_automation/` directory.
    ```bash
    ./start_frontend.sh
    ```
    This will navigate into the `frontend` directory and start the React development server (usually at `http://localhost:5173` or a similar port).

3.  **Access the UI:** Open your web browser and navigate to the frontend URL provided (e.g., `http://localhost:5173`).

## Using the Web UI

*   **Select Target:** Choose a document or directory from the dropdown list under "1. Select Target". These are populated from the `backend/test_documents/` directory.
*   **Select Category:** Optionally select a specific control category (KYC, RGPD, etc.). If left as "Auto-detect", the backend Orchestrator agent will attempt to infer it.
*   **Run Controls:** Click the "Run Controls" button.
*   **View Status & Logs:** The "2. Status & Logs" section will show real-time progress and messages from the backend agents.
*   **View Report:** Once the process completes, the "3. Report" section will appear, showing the path to the generated report file and the Pass/Fail summary (based on LLM grading). Click "View Report Content" to see the full report text.
*   **Manage Prompts:** Use the buttons in the "4. Manage Control Prompts" section to view existing prompts (organized by category) or create new prompt JSON files via a form.

## LLM-Based Grading

The system now uses an LLM (`GraderAgent`) to evaluate the risk associated with each control's result:

*   The Grader LLM is prompted with the control's goal/instructions and its result text.
*   It returns a risk score from 1 (low risk) to 10 (high risk).
*   A score `< 5` (i.e., 1, 2, 3, or 4) is considered **Passed**.
*   A score `>= 5` (or if grading fails) is considered **Failed**.
*   The overall "Tests Passed: X out of Y" summary reflects this threshold.

## Adding New Controls

Use the "Create New Prompt" feature in the Web UI (Section 4) or:

1.  Determine the `meta_category`.
2.  Create the category directory if needed under `backend/prompts/`.
3.  Create a `.json` file in `backend/prompts/<CATEGORY>/`.
4.  Define the required fields: `control_id`, `description`, `meta_category`, `prompt_instructions` (list), `expected_output_format`.

## Key Implementation Notes & TODOs

*   **Vector Search:** Implemented using ChromaDB and OpenAI embeddings (`text-embedding-ada-002`) to process only the top `N_RELEVANT_CHUNKS` (default 3, configurable via env var) per control, significantly speeding up processing for large documents.
*   **PDF Extraction & Chunking:** PDFs are now processed using the Mistral OCR API (`mistral-ocr-latest`), returning structured Markdown. The current `_chunk_text` method uses basic character splitting, which is suboptimal for Markdown; consider implementing Markdown-aware chunking (e.g., splitting by headers/paragraphs) for better semantic context.
*   **LLM Configuration:** API keys must be configured in `.env` for:
    *   OpenAI (`OPENAI_API_KEY`): Used for text embeddings in `ExtractorAgent` and `ControllerAgent`.
    *   Mistral AI (`MISTRAL_API_KEY`): Used for PDF OCR in `ExtractorAgent`.
    *   Controller/Grader LLMs (e.g., `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`): Depending on the models chosen (`CONTROLLER_LLM_MODEL`, `GRADER_LLM_MODEL`).
*   **Shared Utilities:** OpenAI embedding logic has been refactored into `backend/utils/embedding_utils.py`.
*   **Reporting (`backend/agents/reporter.py`):** Reports now include `chunk_id` and `distance` for the highest-risk result, providing more context.
*   **Category Determination (`backend/agents/orchestrator.py`):** Logic for determining control category from path/content is basic and could be improved (e.g., using LLM classification).
*   **Prompt Management:** The UI allows viewing and creating prompts; Edit/Delete functionality could be added.
*   **Dependencies:** Ensure `requirements.txt` (Python backend) and `frontend/package.json` (React frontend) are kept up-to-date. Tesseract is no longer required.
