# AIFuse
AI API Processing and Data  Consolidation Tool

# Overall Application Overview
This  application is an **"Integrated API Processing and Consolidation Tool"** that works in two main phases:

## Processing Phase

- **Input:**  
  Reads an input JSON file (with one case per line).

- **API Calls:**  
  For each case, it calls a remote experiment API using token‑based authentication (handled by MSAL).

- **Concurrency:**  
  Supports threading and batching (with an optional curses‑based UI) to process multiple cases concurrently.

- **Logging/Tracking:**  
  It logs errors, tracks which cases have been processed, and writes out the API responses (CSV formatted) to intermediate files.

- **Background Token Refresh:**  
  A background thread continuously refreshes the access token.

## Consolidation Phase

- **Data Loading:**  
  Loads the original JSON cases, the error log, and the API response CSV file.

- **Merging:**  
  Merges these data sources to produce a consolidated CSV file that combines the API response columns, all JSON fields, and an error message column (if any).

- **Output Conversion:**  
  Converts the consolidated CSV into an Excel file using utility functions.

---

# Module-by-Module Breakdown

## 1. `__init__.py`

- **Purpose:**  
  Marks the directory as a Python package.

- **Content:**  
  It is empty (or may contain package initialization code if needed).

## 2. `config.py`

- **Purpose:**  
  Centralizes configuration and shared state.

- **Defines:**  
  - **File Paths:**  
    Both intermediate and final output file paths (e.g., the consolidated CSV, raw API response, error logs, etc.).
  - **API and MSAL Settings:**  
    API URL, experiment ID, and timeout.
  - **Shared Globals:**  
    Variables like `access_token`, `token_lock`, `api_header`, and `msal_app` are defined here for use by authentication functions.
  - **Processing State:**  
    Global counters (`total_cases`, `cases_processed`), locks (`progress_lock`, `details_lock`), and lists (for `processing_details`) for tracking progress.
  - **Flags for Resume/Retry:**  
    `resume_mode`, `retry_401_flag`  
    and a placeholder `ARGS` for command‑line arguments (which is set in `main.py`).

## 3. `auth.py`

- **Purpose:**  
  Contains functions to obtain and refresh the access token using the MSAL library.

- **Key Functions:**
  - **`get_access_token()`**  
    Checks if an MSAL application exists; if not, creates one. Then, it tries to acquire a token silently using existing accounts, and if that fails, acquires it interactively.
  - **`refresh_token(stop_event)`**  
    Runs in a background thread, periodically (every 3600 seconds) refreshing the token by calling `get_access_token()` and updating `config.access_token`.

## 4. `processing.py`

- **Purpose:**  
  Handles the processing phase of the application. This includes reading the input file, making API calls, logging progress, and providing a curses‑based user interface (when enabled).

- **Subsections and Key Functions:**

  ### A. Tracking and File Functions
  - **`load_processed_cases()` / `update_processed_cases(case_number)`**  
    Read and update a tracking file that remembers which cases have been processed.
  - **`load_401_errors()` / `update_401_error(case_number, error_message)` / `clear_401_tracking_file()`**  
    Handle cases that repeatedly return a 401 error.

  ### B. Curses UI for Resume Option
  - **`check_resume_option(stdscr)`**  
    Uses curses to display a prompt (if a processed tracking file exists) and allows the user to choose whether to resume or start fresh; also optionally decides if persistent 401 error cases should be retried.

  ### C. Logging and Progress Helpers
  - **`append_processing_detail(message)`**  
    Appends messages to the global list (`config.processing_details`) used by the UI.
  - **`clear_output_files()`**  
    Clears intermediate files (raw output, API response, and error logs).
  - **`log_api_error(message)` / `log_script_error(message)`**  
    Write error messages to the corresponding log files and also add the message to the processing details list.
  - **`update_progress()`**  
    Increments the processed cases counter (`config.cases_processed`) safely using a lock.

  ### D. Input Parsing
  - **`parse_input_file(file_name)`**  
    Reads the input JSON file, line by line, parses each JSON object, extracts the case number (using the key `"Incidents_IncidentId"`), and returns a list of tuples.

  ### E. API Call and Error Handling
  - **`log_and_write_error(case_number, original_data, error_message)`**  
    Logs an error and updates progress for a given case.
  - **`call_experiment_api(case_number, original_data)`**  
    The core function that makes the API call for each case. It:
    - Uses the shared access token (with proper locking).
    - Sets up the HTTP headers and JSON payload.
    - Implements retry logic for various HTTP errors (401, 400, 429, 500, 502).
    - On success, extracts the CSV text from the API response’s JSON, writes the raw response to one file, and then parses the CSV rows to write them (appending a header if needed) to the API response file.
    - Calls `append_processing_detail` and updates progress and tracking.
  
  ### F. Batch Processing
  - **`process_batch(batch)`**  
    Iterates over a batch of cases and calls `call_experiment_api` for each.

  ### G. Main Processing Loop
  - **`processing_main()`**  
    Orchestrates the entire processing phase. It:
    - Checks the resume mode and clears tracking files if starting fresh.
    - Reads input cases via `parse_input_file`.
    - Filters out already processed cases if resuming.
    - Determines whether to use threading and/or batching (based on command‑line arguments stored in `config.ARGS`).
    - Sets the global `total_cases` and resets `cases_processed`.
    - Starts the token refresh thread.
    - Waits until an access token is available.
    - Dispatches API calls either concurrently (using threads and/or batches) or sequentially.
    - Finally, sets a stop event for the token thread and waits for it to finish.

  ### H. Curses UI Wrapper
  - **`curses_main(stdscr)`**  
    Provides a live UI that shows:
    - A spinner and elapsed time.
    - The count of processed cases out of total.
    - The most recent processing detail messages (from the global list).
    - It launches `processing_main()` in a separate thread, updates the UI periodically, and waits until processing is complete before exiting.

## 5. `consolidation.py`

- **Purpose:**  
  Implements the consolidation phase by loading data from various sources and merging them.

- **Key Functions:**
  - **`load_original_cases(file_name)`**  
    Reads the original JSON file, parses each line, and builds a dictionary mapping case numbers to their JSON objects.
  - **`load_error_log(file_name)`**  
    Reads the API error log file, using a regex to extract the case number, and returns a dictionary mapping case numbers to error messages.
  - **`load_api_responses(file_name)`**  
    Reads the API response file (which may contain mixed text and CSV blocks) and collects candidate CSV rows. It determines the most common column count to choose the valid CSV header, then groups rows by the case number (assumed to be in the first column).
  - **`consolidate_data(original_file, original_cases, error_log, api_header, api_dict, output_csv)`**  
    Merges the data sources:
    - It first creates a union (sorted) of all JSON keys found in the original cases.
    - Then, it builds a final header consisting of the API CSV header plus the JSON keys and an `"Error_Message"` column.
    - For each case in the original file (maintaining input order), it:
      - Inserts placeholder values if an error exists for that case.
      - Otherwise, for each API response row, it appends the corresponding JSON values and an empty error message.
      - If a case has no API response, it fills in `"Missing"` placeholders.
    - Finally, it writes out the consolidated CSV file.

## 6. `utils.py`

- **Purpose:**  
  Contains generic helper functions that are used by the consolidation phase (and potentially elsewhere) to handle CSV files and convert them to Excel.

- **Key Functions:**
  - **`safe_read_csv(file_name)`**  
    Reads a CSV file, ensures that each row is padded to have the same number of columns, and returns a Pandas DataFrame.
  - **`write_csv_to_excel(csv_file, excel_file)`**  
    Converts a CSV file into an Excel file using Pandas and openpyxl, applying basic formatting (e.g., setting cell number format and alignment).

## 7. `main.py`

- **Purpose:**  
  Acts as the entry point for the entire application.

- **Key Actions:**
  - **Argument Parsing:**  
    Uses argparse to read command‑line arguments (input file, number of threads, batch size, output file names, and an option to disable the curses UI).
  - **Configuration Assignment:**  
    Sets `config.ARGS` with the parsed arguments so that other modules (like processing.py) can access them.
  - **Processing Phase Launch:**  
    Depending on whether the user has disabled the UI (`--no-ui`), it either calls `processing.processing_main()` directly or wraps `processing.curses_main` with `curses.wrapper`.
  - **Consolidation Phase Launch:**  
    After processing completes, it loads the original cases, error log, and API responses; then it calls `consolidation.consolidate_data()` to merge everything into a final CSV, and finally uses `utils.write_csv_to_excel()` to convert that CSV into an Excel file.
  - **Output:**  
    It prints messages to indicate the progress of the consolidation phase and that the process is complete.

---

# Relationships Between Modules

- **`config.py`** is the central repository for configuration constants and shared state. All other modules import from it.
- **`auth.py`** uses values from `config.py` (such as API settings and token_lock) and is used by `processing.py` to handle authentication.
- **`processing.py`** contains the bulk of the processing logic and UI. It calls functions from `auth.py` for token management, and it uses the shared state in `config.py` (including command‑line arguments stored in `config.ARGS`).
- **`consolidation.py`** reads output files generated by `processing.py` and merges data. It also references file names and other configuration settings from `config.py`.
- **`utils.py`** provides helper functions for handling CSV and Excel files and is used by `consolidation.py` (and possibly other modules).
- **`main.py`** orchestrates the entire flow by parsing arguments, setting up the shared configuration, and calling the processing and consolidation phases.

---

# Summary

- The application starts in **`main.py`**, which parses the command‑line arguments and stores them in `config.ARGS`.
- **Processing Phase (`processing.py`):**
  - Reads and filters input cases, manages progress tracking, and makes API calls (using `auth.py` for token management).
  - Uses a curses‑based UI (if enabled) to prompt the user and display real‑time progress.
  - Writes API responses and error logs to intermediate files.
- **Consolidation Phase (`consolidation.py`):**
  - Loads original JSON data, error logs, and API responses, and merges them into a final consolidated CSV.
  - Then, `utils.py` is used to convert the CSV into an Excel file.
- Shared settings and global variables are managed in **`config.py`** so that every module can access the necessary configuration without duplication.
- **`auth.py`** is solely responsible for authentication.
- **`main.py`** ties it all together.

---

