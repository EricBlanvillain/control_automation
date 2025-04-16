import React, { useState, useCallback, useRef, useEffect } from 'react';
import axios from 'axios';
import './App.css';

// Updated list of known categories
const KNOWN_META_CATEGORIES = ["KYC", "RGPD", "LCBFT", "MIFID", "RSE", "INTERNAL_REPORTING"];
// Define the backend API URL
const API_URL = import.meta.env.VITE_API_URL || 'http://127.0.0.1:8000'; // Use env var or default

// Define the expected response structure from the backend
interface ControlApiResponse {
  success: boolean;
  message: string;
  report_path?: string | null;
  logs?: string[] | null;
  summary?: string | null;
}

// Define response for listing targets
interface TargetListResponse {
  targets: string[];
}

// New state for prompts
interface PromptDetail { id: string; description: string; file_path: string; }
interface PromptListResponse { prompts_by_category: Record<string, PromptDetail[]>; }
interface CreatePromptData { control_id: string; description: string; meta_category: string; prompt_instructions: string[]; expected_output_format: string; }

// Helper: Textarea to string array
const textareaToStringArray = (text: string): string[] => {
  return text.split('\n').map(line => line.trim()).filter(line => line.length > 0);
};

// Add FullPromptData type matching backend model
interface FullPromptData {
    control_id: string;
    description: string;
    meta_category: string;
    prompt_instructions: string[];
    expected_output_format: string;
    file_path: string;
}

function App() {
  // State variables
  const [targetPath, setTargetPath] = useState<string>(''); // Selected target path
  const [availableTargets, setAvailableTargets] = useState<string[]>([]); // List of targets for dropdown
  const [selectedCategory, setSelectedCategory] = useState<string>(''); // Empty string means auto-detect
  const [isLoading, setIsLoading] = useState<boolean>(false);
  const [isFetchingTargets, setIsFetchingTargets] = useState<boolean>(true);
  const [logs, setLogs] = useState<string[]>(['Welcome! Select a document or directory to start.']);
  const [reportPath, setReportPath] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [reportContent, setReportContent] = useState<string | null>(null);
  const [isLoadingReport, setIsLoadingReport] = useState<boolean>(false);
  const [reportSummary, setReportSummary] = useState<string | null>(null);
  // New state for prompts
  const [showExistingPrompts, setShowExistingPrompts] = useState<boolean>(false);
  const [showCreatePromptForm, setShowCreatePromptForm] = useState<boolean>(false);
  const [existingPrompts, setExistingPrompts] = useState<Record<string, PromptDetail[]>>({});
  const [isLoadingPrompts, setIsLoadingPrompts] = useState<boolean>(false);
  const [promptError, setPromptError] = useState<string | null>(null);
  // New state for create prompt form
  const [newControlId, setNewControlId] = useState('');
  const [newControlDescription, setNewControlDescription] = useState('');
  const [newControlCategory, setNewControlCategory] = useState(KNOWN_META_CATEGORIES[0] || ''); // Default to first category
  const [newControlInstructions, setNewControlInstructions] = useState(''); // Use textarea, convert on submit
  const [newControlFormat, setNewControlFormat] = useState('');
  const [isSavingPrompt, setIsSavingPrompt] = useState(false);

  // State for editing prompts
  const [showEditPromptForm, setShowEditPromptForm] = useState(false);
  const [editingPromptData, setEditingPromptData] = useState<FullPromptData | null>(null);
  const [isUpdatingPrompt, setIsUpdatingPrompt] = useState(false);
  const [isDeletingPrompt, setIsDeletingPrompt] = useState<string | null>(null); // Store path of prompt being deleted

  // --- State for File Upload --- //
  const [uploadedFile, setUploadedFile] = useState<File | null>(null);
  const [uploadedFilePath, setUploadedFilePath] = useState<string | null>(null); // Path returned from backend
  const [isUploading, setIsUploading] = useState<boolean>(false);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [dragActive, setDragActive] = useState<boolean>(false);
  const fileInputRef = useRef<HTMLInputElement>(null);
  // ----------------------------- //

  const logsEndRef = useRef<HTMLDivElement>(null); // Ref for scrolling logs

  // Fetch available targets on component mount
  useEffect(() => {
    const fetchTargets = async () => {
      setIsFetchingTargets(true);
      try {
        const response = await axios.get<TargetListResponse>(`${API_URL}/api/list-targets`);
        if (response.data && Array.isArray(response.data.targets)) {
          setAvailableTargets(response.data.targets);
          // Optionally select the first target by default
          // if (response.data.targets.length > 0) {
          //   setTargetPath(response.data.targets[0]);
          // }
        } else {
           setAvailableTargets([]);
        }
         setError(null); // Clear previous errors
      } catch (err) {
        console.error("Failed to fetch targets:", err);
        setError("Failed to load available targets from backend. Is the backend running?");
        setAvailableTargets([]); // Ensure it's empty on error
      } finally {
        setIsFetchingTargets(false);
      }
    };

    fetchTargets();
  }, []); // Empty dependency array ensures this runs only once on mount

  // Scroll logs to bottom
  const scrollToBottom = () => {
    logsEndRef.current?.scrollIntoView({ behavior: "smooth" });
  };

  React.useEffect(() => {
    scrollToBottom();
  }, [logs]);

  const addLog = useCallback((message: string) => {
    // Basic timestamp prefix
    const timestamp = new Date().toLocaleTimeString();
    setLogs(prev => [...prev, `${timestamp}: ${message}`]);
  }, []);

  // --- File Upload Handler --- //
  const handleFileUpload = async (file: File | null) => {
    if (!file) return;

    setUploadedFile(file);
    setUploadedFilePath(null); // Clear previous path
    setUploadError(null);
    setIsUploading(true);
    addLog(`Uploading file: ${file.name} (${(file.size / 1024).toFixed(1)} KB)`);

    const formData = new FormData();
    formData.append('file', file);

    try {
        const response = await axios.post<{ success: boolean; message: string; file_path?: string; filename?: string }>(`${API_URL}/api/upload-document`, formData, {
            headers: {
                'Content-Type': 'multipart/form-data',
            },
        });

        if (response.data.success && response.data.file_path) {
            addLog(`File uploaded successfully. Path: ${response.data.file_path}`);
            setUploadedFilePath(response.data.file_path);
            // --- CRITICAL: Set the targetPath to the uploaded file's path --- //
            setTargetPath(response.data.file_path);
            // ------------------------------------------------------------- //
            setError(null); // Clear main error if upload succeeds
        } else {
            throw new Error(response.data.message || "Upload failed, path not returned.");
        }
    } catch (err: any) {
        console.error('Error uploading file:', err);
        let message = 'An unknown error occurred during upload.';
        if (axios.isAxiosError(err)) {
            if (err.response) { message = `Upload Error (${err.response.status}): ${err.response.data?.detail || err.message}`; }
            else if (err.request) { message = 'No response received from backend server.'; }
            else { message = `Request setup error: ${err.message}`; }
        } else if (err instanceof Error) { message = err.message; }
        setUploadError(`Upload failed: ${message}`);
        addLog(`Error uploading ${file.name}: ${message}`);
        setUploadedFile(null); // Clear file on error
    } finally {
        setIsUploading(false);
    }
};
// -------------------------- //

  // Handle running the control process
  const handleRunControls = async () => {
    if (!targetPath) {
      setError('Please select a target document or directory.');
      addLog('Error: Target cannot be empty.');
      return;
    }

    setIsLoading(true);
    setError(null);
    setReportPath(null);
    setReportContent(null);
    setReportSummary(null);
    setIsLoadingReport(false);
    setLogs(prev => [prev[0], `${new Date().toLocaleTimeString()}: Starting control process...`]);

    try {
      addLog(`Target: ${targetPath}`);
      addLog(`Category: ${selectedCategory || 'Auto-detect'}`);

      // --- Real API Call ---
      addLog(`Sending request to backend: ${API_URL}/api/run-controls`);
      const response = await axios.post<ControlApiResponse>(
        `${API_URL}/api/run-controls`,
        {
          target_path: targetPath,
          // Send null if category is empty string, otherwise send the value
          category: selectedCategory || null,
        },
        {
          headers: { 'Content-Type': 'application/json' }
        }
      );

      addLog('Backend response received.');

      // Add backend logs to the frontend logs
      if (response.data.logs && Array.isArray(response.data.logs)) {
        response.data.logs.forEach(log => addLog(`[Backend] ${log}`));
      }

      if (response.data.success) {
        addLog(`Processing complete. ${response.data.message}`);
        setReportPath(response.data.report_path || null);
        setReportSummary(response.data.summary || null);
      } else {
        addLog(`Backend processing failed: ${response.data.message}`);
        setError(`Processing failed: ${response.data.message}`);
      }
      // --- End Real API Call ---

    } catch (err: any) {
      console.error('Error running controls:', err);
      let message = 'An unknown error occurred';
      if (axios.isAxiosError(err)) {
        // Handle Axios-specific errors (network error, timeout, bad response)
        if (err.response) {
          // The request was made and the server responded with a status code
          // that falls out of the range of 2xx
          console.error("Backend Error Data:", err.response.data);
          console.error("Backend Error Status:", err.response.status);
          message = `Backend Error (${err.response.status}): ${err.response.data?.detail || err.message}`;
        } else if (err.request) {
          // The request was made but no response was received
          message = 'No response received from backend server. Is it running?';
        } else {
          // Something happened in setting up the request that triggered an Error
          message = `Request setup error: ${err.message}`;
        }
      } else if (err instanceof Error) {
        message = err.message;
      }
      setError(`Failed to run controls: ${message}`);
      addLog(`Error: ${message}`);
    } finally {
      setIsLoading(false);
    }
  };

  // Handle fetching report content
  const handleViewReport = async () => {
    if (!reportPath) return;

    setIsLoadingReport(true);
    setError(null);
    setReportContent(null); // Clear previous content
    addLog(`Fetching content for report: ${reportPath}`);

    try {
      const response = await axios.get<string>( // Expect plain text response
        `${API_URL}/api/get-report-content`,
        {
          params: { report_path: reportPath }, // Send path as query parameter
        }
      );
      setReportContent(response.data);
      addLog('Report content loaded.');
    } catch (err: any) {
        console.error('Error fetching report content:', err);
        let message = 'An unknown error occurred';
        if (axios.isAxiosError(err)) {
          if (err.response) {
            message = `Backend Error (${err.response.status}): ${err.response.data?.detail || err.response.data || err.message}`;
          } else if (err.request) {
            message = 'No response received from backend server.';
          } else {
            message = `Request setup error: ${err.message}`;
          }
        } else if (err instanceof Error) {
          message = err.message;
        }
        setError(`Failed to load report content: ${message}`);
        addLog(`Error loading report: ${message}`);
    } finally {
      setIsLoadingReport(false);
    }
  };

  // Fetch existing prompts
  const fetchExistingPrompts = async () => {
    setIsLoadingPrompts(true);
    setPromptError(null);
    addLog('Fetching existing control prompts...');
    try {
      const response = await axios.get<PromptListResponse>(`${API_URL}/api/list-prompts`);
      setExistingPrompts(response.data?.prompts_by_category || {});
      addLog(`Found prompts in ${Object.keys(response.data?.prompts_by_category || {}).length} categories.`);
    } catch (err) {
      console.error("Failed to fetch prompts:", err);
      setPromptError("Failed to load existing prompts from backend.");
      addLog("Error fetching prompts.");
      setExistingPrompts({});
    } finally {
      setIsLoadingPrompts(false);
    }
  };

  // Handle showing existing prompts
  const handleShowExistingPrompts = () => {
    setShowCreatePromptForm(false); // Hide create form if open
    setShowExistingPrompts(prev => !prev); // Toggle visibility
    if (!showExistingPrompts && Object.keys(existingPrompts).length === 0) {
        // Fetch only if opening and not already fetched
        fetchExistingPrompts();
    }
    // Close edit/create forms when toggling view
    setShowEditPromptForm(false);
    setEditingPromptData(null);
  };

  // Handle showing create prompt form
  const handleShowCreatePrompt = () => {
      setShowExistingPrompts(false); // Hide existing list if open
      setShowCreatePromptForm(prev => !prev); // Toggle visibility
      setPromptError(null); // Clear any previous errors
      // Reset create form fields if opening
      if (!showCreatePromptForm) {
         resetCreateFormFields();
      }
  };

  // Handle saving a new prompt
  const handleSavePrompt = async (event: React.FormEvent) => {
      event.preventDefault(); // Prevent default form submission
      if (!newControlId || !newControlDescription || !newControlCategory || !newControlInstructions || !newControlFormat) {
          setPromptError("All fields are required to create a prompt.");
          return;
      }

      const instructionsArray = textareaToStringArray(newControlInstructions);
      if (instructionsArray.length === 0) {
          setPromptError("Prompt Instructions cannot be empty.");
          return;
      }

      // Basic ID validation (matches backend pattern)
      if (!/^[A-Z0-9_]+$/.test(newControlId)) {
         setPromptError("Control ID can only contain uppercase letters, numbers, and underscores.");
         return;
      }

      const newPromptData: CreatePromptData = {
          control_id: newControlId,
          description: newControlDescription,
          meta_category: newControlCategory,
          prompt_instructions: instructionsArray,
          expected_output_format: newControlFormat
      };

      setIsSavingPrompt(true);
      setPromptError(null);
      addLog(`Attempting to save new prompt: ${newControlId}`);

      try {
          await axios.post(`${API_URL}/api/create-prompt`, newPromptData, { headers: { 'Content-Type': 'application/json' } });
          addLog(`Successfully saved prompt: ${newControlId}`);
          // Clear form and close it
          setNewControlId('');
          setNewControlDescription('');
          setNewControlInstructions('');
          setNewControlFormat('');
          // Reset category or keep it?
          // setNewControlCategory(KNOWN_META_CATEGORIES[0] || '');
          setShowCreatePromptForm(false);
          // Refresh the existing prompts list if it was open
          if (showExistingPrompts) {
              fetchExistingPrompts();
          }
          alert('Prompt created successfully!'); // Simple user feedback
      } catch (err: any) {
        console.error('Error saving prompt:', err);
        let message = 'An unknown error occurred saving the prompt.';
        if (axios.isAxiosError(err)) {
            if (err.response) { message = `Backend Error (${err.response.status}): ${err.response.data?.detail || err.message}`; }
            else if (err.request) { message = 'No response received from backend server.'; }
            else { message = `Request setup error: ${err.message}`; }
        } else if (err instanceof Error) { message = err.message; }
        setPromptError(`Failed to save prompt: ${message}`);
        addLog(`Error saving prompt ${newControlId}: ${message}`);
      } finally {
          setIsSavingPrompt(false);
      }
  };

  // --- Edit/Delete Prompt Handlers ---
  const handleEditPrompt = async (prompt: PromptDetail) => {
      console.log("Editing prompt:", prompt.file_path);
      setPromptError(null);
      setShowCreatePromptForm(false); // Close create form if open
      // Fetch full details to populate edit form
      try {
          const response = await fetch(`${API_URL}/api/prompt-details?file_path=${encodeURIComponent(prompt.file_path)}`);
          if (!response.ok) {
              const errorData = await response.json();
              throw new Error(errorData.detail || `Failed to fetch prompt details (status ${response.status})`);
          }
          const data: FullPromptData = await response.json();
          // Store the data directly, conversion happens in the form
          setEditingPromptData(data);
          setShowEditPromptForm(true);
      } catch (err) {
          const errorMsg = err instanceof Error ? err.message : String(err);
          console.error("Fetch Prompt Details Error:", err);
          setPromptError(`Failed to load prompt details: ${errorMsg}`);
          setEditingPromptData(null);
          setShowEditPromptForm(false);
      }
  };

  const handleDeletePrompt = async (prompt: PromptDetail) => {
      const confirmDelete = window.confirm(`Are you sure you want to delete the prompt '${prompt.id}' (${prompt.file_path})? This cannot be undone.`);
      if (!confirmDelete) {
          return;
      }

      console.log("Deleting prompt:", prompt.file_path);
      setPromptError(null);
      setIsDeletingPrompt(prompt.file_path); // Set loading state for this specific prompt

      try {
          const response = await fetch(`${API_URL}/api/delete-prompt?file_path=${encodeURIComponent(prompt.file_path)}`, {
              method: 'DELETE',
          });

          if (!response.ok) {
              const errorData = await response.json();
              throw new Error(errorData.detail || `Failed to delete prompt (status ${response.status})`);
          }

          // Success
          const successData = await response.json();
          console.log("Delete success:", successData);
          addLog(`Prompt deleted successfully: ${prompt.file_path}`);
          fetchExistingPrompts(); // Refresh the prompt list

      } catch (err) {
          const errorMsg = err instanceof Error ? err.message : String(err);
          console.error("Delete Prompt Error:", err);
          setPromptError(`Failed to delete prompt: ${errorMsg}`);
      } finally {
          setIsDeletingPrompt(null); // Clear loading state
      }
  };

  const handleSaveUpdatePrompt = async (event: React.FormEvent) => {
      event.preventDefault();
      if (!editingPromptData) return;
      console.log("Saving updated prompt:", editingPromptData.file_path);
      setPromptError(null);
      setIsUpdatingPrompt(true);

      // Prepare data for the API (ensure instructions are an array)
      const updatePayload = {
          file_path: editingPromptData.file_path,
          description: editingPromptData.description,
          meta_category: editingPromptData.meta_category,
          prompt_instructions: editingPromptData.prompt_instructions.filter(line => line.trim().length > 0), // Send cleaned array
          expected_output_format: editingPromptData.expected_output_format
      };

      try {
          const response = await fetch(`${API_URL}/api/update-prompt`, {
              method: 'PUT',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify(updatePayload)
          });

          if (!response.ok) {
              const errorData = await response.json();
              throw new Error(errorData.detail || `Failed to update prompt (status ${response.status})`);
          }

          // Success
          const successData = await response.json();
          console.log("Update success:", successData);
          addLog(`Prompt updated successfully: ${successData.new_file_path || editingPromptData.file_path}`);
          setShowEditPromptForm(false);
          setEditingPromptData(null);
          fetchExistingPrompts(); // Refresh the prompt list

      } catch (err) {
          const errorMsg = err instanceof Error ? err.message : String(err);
          console.error("Update Prompt Error:", err);
          setPromptError(`Failed to update prompt: ${errorMsg}`);
          // Keep the form open with current data in case of error
      } finally {
          setIsUpdatingPrompt(false);
      }
  };

  const handleCancelEdit = () => {
      setShowEditPromptForm(false);
      setEditingPromptData(null);
      setPromptError(null);
  };

  // --- Helper to reset Create form fields ---
  const resetCreateFormFields = () => {
      setNewControlId('');
      setNewControlDescription('');
      setNewControlCategory(KNOWN_META_CATEGORIES[0] || ''); // Reset to first known category or empty
      setNewControlInstructions('');
      setNewControlFormat('');
  };

  return (
    <div id="App">
      <h1>Control Automation</h1>

      {/* Input & Config Section */}
      <div className="card input-config-section">
        <h2>1. Configure & Run</h2>
        <div className="control-group">
          <label htmlFor="targetPath">Target Document / Directory:</label>
          {isFetchingTargets ? (
            <p>Loading available targets...</p>
          ) : availableTargets.length > 0 ? (
            <select
              id="targetPath"
              value={targetPath}
              onChange={(e) => setTargetPath(e.target.value)}
              disabled={isLoading}
            >
              <option value="" disabled>-- Select a Target --</option>
              {availableTargets.map(target => (
                <option key={target} value={target}>{target}</option>
              ))}
            </select>
          ) : (
            <p>No targets found in configured directory (<code>test_documents/</code>). Check backend logs.</p>
          )}
        </div>

        {/* --- File Upload Section --- */}
        <div className="control-group">
          <label>Or Upload Document:</label>
          <div
            className={`drop-zone ${dragActive ? 'drop-zone-active' : ''}`}
            onDragEnter={(e) => { e.preventDefault(); e.stopPropagation(); setDragActive(true); }}
            onDragLeave={(e) => { e.preventDefault(); e.stopPropagation(); setDragActive(false); }}
            onDragOver={(e) => { e.preventDefault(); e.stopPropagation(); /* Required to allow drop */ }}
            onDrop={(e) => {
              e.preventDefault();
              e.stopPropagation();
              setDragActive(false);
              if (e.dataTransfer.files && e.dataTransfer.files[0]) {
                handleFileUpload(e.dataTransfer.files[0]);
              }
            }}
            onClick={() => fileInputRef.current?.click()} // Trigger hidden file input
          >
            <input
              ref={fileInputRef}
              type="file"
              style={{ display: 'none' }} // Hide the actual input
              onChange={(e) => {
                if (e.target.files && e.target.files[0]) {
                  handleFileUpload(e.target.files[0]);
                }
              }}
              accept=".txt,.pdf,.docx,.xlsx" // Specify acceptable file types
            />
            {isUploading ? (
              <p>Uploading...</p>
            ) : uploadedFile ? (
              <p>Selected: {uploadedFile.name}</p>
            ) : (
              <p>Drag 'n' drop file here, or click to select</p>
            )}
          </div>
          {uploadedFilePath && (
            <div className="upload-info">
              <span>Using uploaded file: <code>{uploadedFilePath}</code></span>
              <button
                className="clear-upload-button"
                onClick={() => {
                  setUploadedFile(null);
                  setUploadedFilePath(null);
                  setTargetPath(''); // Clear target path
                  setUploadError(null);
                }}
              >
                Clear
              </button>
            </div>
          )}
          {uploadError && <p className="error-message upload-error-text">{uploadError}</p>}
        </div>
        {/* ------------------------- */}

        <div className="control-group">
          <label htmlFor="category">Control Category (Optional):</label>
          <select
            id="category"
            value={selectedCategory}
            onChange={(e) => setSelectedCategory(e.target.value)}
            disabled={isLoading || !targetPath} // Also disable if no target selected
          >
            <option value="">Auto-detect from Path</option>
            {KNOWN_META_CATEGORIES.map(cat => (
              <option key={cat} value={cat}>{cat}</option>
            ))}
          </select>
        </div>

        <div className="control-group">
          <button
            onClick={handleRunControls}
            disabled={isLoading || !targetPath}
            className="run-button"
          >
            {isLoading && <span className="spinner"></span>}
            {isLoading ? 'Processing' : 'Run Controls'}
          </button>
        </div>
      </div>

      {error &&
        <div className="card error-message">
          Error: {error}
        </div>
      }

      {/* Logs Section */}
      <div className="card logs-section">
        <h2>2. Status & Logs</h2>
        <pre>
          {logs.join('\n')}
          <div ref={logsEndRef} />
        </pre>
      </div>

      {/* --- Results Section - Always Visible Card --- */}
      <div className="card results-section">
        <h2>3. Report</h2>

        {/* --- Conditionally Rendered Content INSIDE Card --- */}

        {/* Placeholder message when no report exists yet */}
        {!reportPath && !reportContent && !isLoadingReport && !isLoading && (
             <p>Run controls on a document first to generate a report.</p>
        )}

        {/* Display path if it exists */}
        {reportPath && <p>Report generated at: <code>{reportPath}</code></p>}

        {/* Display summary if it exists */}
        {reportSummary && <p><strong>{reportSummary}</strong></p>}

        {/* Show button only if path exists and content isn't loaded/loading */}
        {reportPath && !reportContent && !isLoadingReport && (
            <button className='view-report-button' onClick={handleViewReport} disabled={isLoadingReport}>
              View Report Content
            </button>
        )}

        {/* Show loading indicator */}
        {isLoadingReport && <p>Loading report content...</p>}

        {/* Display fetched report content */}
        {reportContent && (
          <div className="report-content">
            {/* Removed redundant H3 title */}
            <pre>{reportContent}</pre>
          </div>
        )}
        {/* --- End of Conditional Content --- */}
      </div>

      {/* --- Prompts Section (View/Create/Edit/Delete) --- */}
      <div className="card prompts-section">
        <h2>4. Manage Control Prompts</h2>
        <div className="prompt-actions">
            <button onClick={handleShowExistingPrompts} disabled={isLoadingPrompts || isUpdatingPrompt || !!isDeletingPrompt}>
                {showExistingPrompts ? 'Hide' : 'View'} Existing Prompts {isLoadingPrompts ? '(Loading...)' : ''}
            </button>
            <button onClick={handleShowCreatePrompt} disabled={isSavingPrompt || isUpdatingPrompt || !!isDeletingPrompt}>
                 {showCreatePromptForm ? 'Cancel Create' : 'Create New'} Prompt
            </button>
        </div>

        {promptError && <div className="error-message prompt-error">{promptError}</div>}

        {/* View Existing Prompts Area - ADD EDIT/DELETE BUTTONS */}
        {showExistingPrompts && !isLoadingPrompts && (
            <div className="existing-prompts-list">
                {Object.keys(existingPrompts).length > 0 ? (
                    Object.entries(existingPrompts).map(([category, prompts]) => (
                        <div key={category} className="prompt-category">
                            <h3>{category}</h3>
                            {prompts.length > 0 ? (
                                <ul>
                                    {prompts.map(prompt => (
                                        <li key={prompt.file_path}>
                                            <span>
                                                <strong>{prompt.id}:</strong> {prompt.description} <i>({prompt.file_path})</i>
                                            </span>
                                            <div className="prompt-item-actions">
                                                <button
                                                    onClick={() => handleEditPrompt(prompt)}
                                                    disabled={isUpdatingPrompt || !!isDeletingPrompt || showEditPromptForm || showCreatePromptForm}
                                                    className="edit-button">
                                                    Edit
                                                </button>
                                                <button
                                                    onClick={() => handleDeletePrompt(prompt)}
                                                    disabled={isUpdatingPrompt || !!isDeletingPrompt || isDeletingPrompt === prompt.file_path}
                                                    className="delete-button">
                                                    {isDeletingPrompt === prompt.file_path ? 'Deleting...' : 'Delete'}
                                                </button>
                                            </div>
                                        </li>
                                    ))}
                                </ul>
                            ) : (
                                <p>No prompts found in this category.</p>
                            )}
                        </div>
                    ))
                ) : (
                    <p>No existing prompts found in the <code>backend/prompts/</code> directory.</p>
                )}
            </div>
        )}

        {/* --- Edit Prompt Form --- */}
        {showEditPromptForm && editingPromptData && (
           <form className="edit-prompt-form" onSubmit={handleSaveUpdatePrompt}>
              <h3>Edit Prompt: {editingPromptData.control_id}</h3>
              <p><i>File: {editingPromptData.file_path}</i></p>
              {/* ID is not editable */}
              <div className="control-group">
                  <label htmlFor="editControlDescription">Description:</label>
                  <input
                      type="text"
                      id="editControlDescription"
                      value={editingPromptData.description}
                      onChange={e => setEditingPromptData(prev => prev ? {...prev, description: e.target.value} : null)}
                      required
                  />
              </div>
              <div className="control-group">
                  <label htmlFor="editControlCategory">Meta Category:</label>
                  <select
                      id="editControlCategory"
                      value={editingPromptData.meta_category}
                      onChange={e => setEditingPromptData(prev => prev ? {...prev, meta_category: e.target.value} : null)}
                      required
                  >
                       {KNOWN_META_CATEGORIES.map(cat => (<option key={cat} value={cat}>{cat}</option>))}
                  </select>
              </div>
              <div className="control-group">
                  <label htmlFor="editControlInstructions">Prompt Instructions (one per line):</label>
                  <textarea
                      id="editControlInstructions"
                      value={editingPromptData.prompt_instructions.join('\n')}  // Join array for display
                      onChange={e => setEditingPromptData(prev => prev ? {...prev, prompt_instructions: e.target.value.split('\n')} : null)}
                      required
                      rows={5}
                  />
              </div>
               <div className="control-group">
                  <label htmlFor="editControlFormat">Expected Output Format:</label>
                  <input
                      type="text"
                      id="editControlFormat"
                      value={editingPromptData.expected_output_format}
                      onChange={e => setEditingPromptData(prev => prev ? {...prev, expected_output_format: e.target.value} : null)}
                      required
                  />
              </div>
              <div className="form-actions">
                  <button
                      type="submit"
                      className="save-prompt-button"
                      disabled={isUpdatingPrompt}
                  >
                      {isUpdatingPrompt ? 'Saving Changes...' : 'Save Changes'}
                  </button>
                  <button
                      type="button"
                      onClick={handleCancelEdit}
                      disabled={isUpdatingPrompt}
                      className="cancel-button"
                  >
                      Cancel
                  </button>
              </div>
          </form>
        )}

        {/* Create New Prompt Form */}
        {showCreatePromptForm && (
            <form className="create-prompt-form" onSubmit={handleSavePrompt}>
                <h3>Create New Prompt JSON</h3>
                <div className="control-group">
                    <label htmlFor="newControlId">Control ID (e.g., CATEGORY_00X):</label>
                    <input type="text" id="newControlId" value={newControlId} onChange={e => setNewControlId(e.target.value.toUpperCase())} required pattern="^[A-Z0-9_]+$" title="Use only uppercase letters, numbers, and underscores." />
                </div>
                <div className="control-group">
                    <label htmlFor="newControlDescription">Description:</label>
                    <input type="text" id="newControlDescription" value={newControlDescription} onChange={e => setNewControlDescription(e.target.value)} required />
                </div>
                <div className="control-group">
                    <label htmlFor="newControlCategory">Meta Category:</label>
                    <select id="newControlCategory" value={newControlCategory} onChange={e => setNewControlCategory(e.target.value)} required>
                         {KNOWN_META_CATEGORIES.map(cat => (<option key={cat} value={cat}>{cat}</option>))}
                    </select>
                </div>
                <div className="control-group">
                    <label htmlFor="newControlInstructions">Prompt Instructions (one per line):</label>
                    <textarea id="newControlInstructions" value={newControlInstructions} onChange={e => setNewControlInstructions(e.target.value)} required rows={5}></textarea>
                </div>
                 <div className="control-group">
                    <label htmlFor="newControlFormat">Expected Output Format (e.g., JSON, String):</label>
                    <input type="text" id="newControlFormat" value={newControlFormat} onChange={e => setNewControlFormat(e.target.value)} required />
                </div>
                <button type="submit" className="save-prompt-button" disabled={isSavingPrompt}>
                    {isSavingPrompt ? 'Saving...' : 'Save New Prompt'}
                </button>
            </form>
        )}
      </div>

    </div>
  );
}

export default App;
