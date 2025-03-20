# AIFuse

**AIFuse** is an integrated API processing and data consolidation tool designed to process cases in an isolated, concurrent, and robust manner. The application reads a JSON file (with one case per line), calls a remote AI API for each case, and then consolidates the API responses together with the original case data into a final CSV and Excel output. Each processing job runs independently with its own progress tracking, logging, and file outputs.

---

## Overall Application Overview

AIFuse is organized into two primary phases:

1. **Processing Phase:**  
   - **Input:** Reads a JSON file containing multiple cases.
   - **API Calls:** For each case, the app calls a remote experiment API using token‑based authentication (handled via MSAL).
   - **Job Isolation:** Each job (a set of cases) runs independently with its own dedicated files and in‑memory state. This includes independent progress tracking, error logging, and output file generation.
   - **Concurrency:** Supports multithreading and batching so multiple cases can be processed concurrently.
   - **Error Handling:** Implements robust error handling and retry logic (including 401, 400, 429, 500, and 502 errors). Both API errors and script errors are logged to dedicated per‑job files.
   - **Token Refresh:** A background thread refreshes the access token periodically so that API calls remain authenticated throughout processing.

2. **Consolidation Phase:**  
   - **Data Merging:** Loads the original case data, API response CSVs, and error log files.
   - **Integration:** Merges all sources into a consolidated CSV file that includes columns for the API responses, all original JSON fields, and any error messages.
   - **Output Conversion:** Converts the consolidated CSV into an Excel file for easier review.

The tool can run in a headless mode, a curses‑based terminal UI mode, or a full Tkinter graphical UI. In multi‑job mode (via the Tkinter UI), each job runs completely isolated from others—even though they share a common access token.

---

## Module-by-Module Breakdown

### 1. `auth.py`
- **Purpose:**  
  Manages authentication with the remote API using the Microsoft Authentication Library (MSAL).
- **Key Functions:**
  - `get_access_token()`:  
    Initializes the MSAL client (if needed), attempts to acquire a token silently, and falls back to interactive login if necessary.
  - `refresh_token(stop_event)`:  
    Runs as a background thread to periodically refresh the access token (every 3600 seconds).

### 2. `config.py`
- **Purpose:**  
  Centralizes configuration settings and shared global variables.
- **Key Items:**
  - **Paths:**  
    Defines default paths for outputs (consolidated CSV/Excel, raw API responses, error logs, tracking files).
  - **API Settings:**  
    Stores API URL, experiment ID, timeout, and MSAL client details.
  - **Global State:**  
    Contains globals for authentication (e.g., `access_token`, `token_lock`) and processing state (e.g., `processing_details`, `progress_lock`).
  - **Utility Function:**  
    `generate_filename()` creates consistent file names based on the input file’s MD5 hash, the experiment ID, and a basename.

### 3. `consolidation.py`
- **Purpose:**  
  Implements the consolidation phase, merging data from different sources.
- **Key Functions:**
  - `load_original_cases(file_name)`:  
    Reads the original JSON file, mapping case numbers to their JSON data.
  - `load_error_log(file_name)`:  
    Reads the error log file (using a regex to extract case numbers) and returns a dictionary of error messages.
  - `load_api_responses(file_name)`:  
    Reads the API response CSV file (handling inconsistent CSV formatting) and groups rows by case number.
  - `consolidate_data(original_file, original_cases, error_log, api_header, api_dict, output_csv)`:  
    Combines API responses, JSON data, and error messages into a final CSV file.

### 4. `curses_ui.py`
- **Purpose:**  
  Provides a terminal-based (curses) user interface.
- **Key Features:**
  - Displays a live spinner, elapsed time, and counts of processed cases.
  - Prompts the user for resume/start-fresh options.
  - Launches processing in a background thread and updates the UI until processing completes.

### 5. `job_manager.py`
- **Purpose:**  
  Defines the `Job` class and handles job state persistence.
- **Key Features:**
  - **Job Class:**  
    Represents a processing job, storing its input file, experiment ID, and dedicated file paths for outputs.  
    New per-job state attributes include:
    - `progress_total` and `progress_done` (for progress tracking)
    - `processing_details` (an in-memory log for the job)
    - `resume_mode` and `retry_401_flag` (for resume and retry behavior)
  - **Persistence Functions:**  
    Functions to save, load, and clear job state from disk (as JSON files).

### 6. `log_config.py`
- **Purpose:**  
  Configures the application’s logging.
- **Key Features:**
  - Sets up logging to both a file and the console.
  - Ensures that the output directory exists and creates a common application log file (`app.log`).

### 7. `main.py`
- **Purpose:**  
  Serves as the entry point for the application.
- **Key Responsibilities:**
  - Parses command‑line arguments (input file, threads, batch size, etc.) and sets `config.ARGS`.
  - Validates configuration values.
  - Chooses the UI mode (curses, Tkinter, or headless) and launches the processing phase.
  - After processing, initiates the consolidation phase and converts the consolidated CSV to Excel.

### 8. `processing.py`
- **Purpose:**  
  Contains the core logic for the processing phase.
- **Key Responsibilities:**
  - **Tracking Functions:**  
    Functions such as `load_processed_cases()`, `update_processed_cases()`, and error-tracking functions manage per-job tracking files.
  - **User Prompt:**  
    `check_resume_option()` uses curses to prompt the user regarding resuming previous runs.
  - **Logging & Progress:**  
    Helper functions (`append_processing_detail()`, `log_api_error()`, `log_script_error()`, `update_progress()`) write messages both to per-job in-memory logs and to dedicated files.
  - **Input Parsing:**  
    `parse_input_file()` reads the JSON file, extracting case numbers.
  - **API Calls:**  
    `call_experiment_api()` (for non-job mode) and `call_experiment_api_job()` (for job mode) perform the API calls with robust error handling and retry logic.
  - **Batch Processing & Threading:**  
    Functions to process cases in batches or using threads.
  - **Processing Loops:**  
    `processing_main()` handles non-job mode; `processing_main_job(job)` runs a job in isolation, updating progress, writing outputs, and handling errors.

### 9. `utils.py`
- **Purpose:**  
  Contains utility functions.
- **Key Functions:**
  - `safe_read_csv(file_name)`:  
    Reads a CSV file into a Pandas DataFrame, ensuring that rows have a consistent number of columns.
  - `write_csv_to_excel(csv_file, excel_file)`:  
    Converts a CSV file into an Excel file with basic formatting.
  - `check_resume_status()`:  
    Determines whether there is a previous run that can be resumed by comparing the total input cases to the number already processed.

### 10. `win_ui.py`
- **Purpose:**  
  Provides a graphical user interface using Tkinter.
- **Key Features:**
  - Displays a list of jobs and their statuses.
  - Each job runs in its own tab with a dedicated progress bar and log area.
  - Offers controls to start new jobs, stop all jobs, and clear job state.
  - Ensures that each job’s UI components (progress bar, log window) update independently from one another.

---

## Relationships Between Modules

- **Configuration and Globals:**  
  `config.py` centralizes settings and shared global state (e.g., token, file paths). Other modules import this to access configuration data.

- **Authentication:**  
  `auth.py` manages token acquisition and refresh and relies on configuration from `config.py`.

- **Job Management & Isolation:**  
  The `Job` class (in `job_manager.py`) encapsulates per-job state (files, progress, logs). Both `processing.py` and `win_ui.py` interact with Job objects to ensure isolated processing.

- **Processing & Consolidation:**  
  `processing.py` handles case processing (API calls, error handling, progress updates) and writes intermediate files. Once processing is complete, `consolidation.py` reads these files to merge the original case data, API responses, and errors into a final output.  
  - `utils.py` supports consolidation by providing CSV-to-Excel conversion functions.

- **User Interfaces:**  
  Two separate UIs exist:
  - **Curses UI (curses_ui.py):** Provides a terminal-based interface for processing.
  - **Tkinter UI (win_ui.py):** Allows for multi-job management, showing each job’s progress and logs in separate tabs.

- **Entry Point:**  
  `main.py` ties everything together by parsing command‑line arguments, validating configuration, and launching either a UI or headless processing mode, followed by consolidation.

---

## Summary

AIFuse is a comprehensive tool for processing case data through API calls and consolidating the results into a final, reviewable format. Its key features:

- **Isolated Job Processing:**  
  Each job is managed independently with dedicated files and in‑memory state, ensuring that errors, progress, and outputs remain isolated between jobs.

- **Robust Concurrency:**  
  The tool supports multithreading and batching to process cases quickly, with careful management of a shared authentication token.

- **Error Handling and Logging:**  
  Errors are tracked and logged both to dedicated files and to per‑job in‑memory logs, ensuring that every processed case (whether successful or erroneous) is accounted for.

- **Flexible User Interfaces:**  
  With both a curses‑based UI and a full Tkinter GUI, users can monitor processing in real time, manage multiple jobs, and consolidate the results into CSV and Excel outputs.

- **Modular Design:**  
  The application is organized into clear modules (configuration, authentication, job management, processing, consolidation, utilities, and UI) that interact in a well‑defined manner, facilitating both maintenance and future enhancements.


---


