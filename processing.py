import os
import sys
import threading
import requests
import json
import time
import csv
import curses
import itertools
import re
from queue import Queue
from threading import Semaphore
from log_config import logger
import config
from auth import get_access_token, refresh_token
import utils  # Contains the shared utilities (e.g., check_resume_status)

# --- Tracking File Functions ---
def load_processed_cases(job):
    processed = set()
    if os.path.exists(job.processed_tracking_file):
        with open(job.processed_tracking_file, 'r') as f:
            for line in f:
                processed.add(line.strip())
    return processed

def update_processed_cases(job, case_number):
    with job.tracking_file_lock:  # Use lock to ensure thread safety
        with open(job.processed_tracking_file, 'a') as f:
            f.write(str(case_number) + "\n")

def load_401_errors(job):
    errors = set()
    if os.path.exists(job.api_401_tracking_file):
        with open(job.api_401_tracking_file, 'r') as f:
            for line in f:
                case = line.strip()
                if case:
                    errors.add(case)
    return errors

def update_401_error(job, case_number, error_message):
    with job.api_401_lock:  # Use lock for thread safety
        with open(job.api_401_tracking_file, 'a') as f:
            f.write(str(case_number) + "\n")
    append_processing_detail(job, f"Case {case_number}: 401 error logged.")

def clear_401_tracking_file(job):
    if os.path.exists(job.api_401_tracking_file):
        with open(job.api_401_tracking_file, 'w') as f:
            f.write("")

# --- Curses Prompt for Resume/Start Fresh ---
def check_resume_option(stdscr, job):
    status = utils.check_resume_status()
    total_input = status["total_input"]
    processed_count = status["processed_count"]
    
    if os.path.exists(job.processed_tracking_file) and processed_count > 0:
        if processed_count >= total_input:
            stdscr.clear()
            stdscr.addstr(0, 0, f"All {total_input} cases are already processed. Nothing to resume.")
            stdscr.refresh()
            time.sleep(2)
            curses.endwin()
            sys.exit(0)
        else:
            stdscr.clear()
            stdscr.addstr(0, 0, "Previous run detected.")
            logger.info("Previous run detected.")
            stdscr.addstr(1, 0, f"Processed cases: {processed_count}. Total input cases: {total_input}.")
            stdscr.addstr(2, 0, "Press 'R' to resume processing remaining cases, or 'S' to start fresh:")
            stdscr.refresh()
            while True:
                key = stdscr.getch()
                if key in (ord('r'), ord('R')):
                    job.resume_mode = True
                    logger.info("Resuming Previous Run.")
                    break
                elif key in (ord('s'), ord('S')):
                    job.resume_mode = False
                    logger.info("Starting Fresh Run.")
                    break
            stdscr.addstr(3, 0, f"User selected: {'RESUME' if job.resume_mode else 'START FRESH'}.")
            stdscr.refresh()
            time.sleep(2)
            if job.resume_mode and os.path.exists(job.api_401_tracking_file):
                with open(job.api_401_tracking_file, 'r') as f:
                    retry_lines = [line.strip() for line in f if line.strip()]
                if retry_lines:
                    stdscr.addstr(4, 0, f"There are {len(retry_lines)} cases with persistent 401 errors.")
                    logger.info("Cases with 401 Errors Found.")
                    stdscr.addstr(5, 0, "Press 'R' to retry these 401 errors, or 'S' to skip them:")
                    stdscr.refresh()
                    while True:
                        key = stdscr.getch()
                        if key in (ord('r'), ord('R')):
                            job.retry_401_flag = True
                            logger.info("Retrying Cases with 401 Errors.")
                            break
                        elif key in (ord('s'), ord('S')):
                            job.retry_401_flag = False
                            logger.info("Cases with 401 Errors Ignored.")
                            break
                    stdscr.addstr(6, 0, f"User selected: {'Retry 401 errors' if job.retry_401_flag else 'Skip 401 errors'}.")
                    stdscr.refresh()
                    time.sleep(2)
    else:
        job.resume_mode = False

# --- Logging and Progress Helpers ---
def append_processing_detail(job, message):
    if job is not None:
        if not hasattr(job, 'processing_details'):
            job.processing_details = []
        job.processing_details.append(message)
        job.log(message)
    else:
        with config.details_lock:
            config.processing_details.append(message)
            if len(config.processing_details) > 20:
                config.processing_details.pop(0)

def clear_output_files(job):
    output_files = [job.raw_output_file, job.api_response_file, job.api_error_log_file, job.script_error_log_file, job.api_401_tracking_file]
    for file_name in output_files:
        with open(file_name, 'w') as file:
            file.write("")
    append_processing_detail(job, "Output files cleared.")
    print("Output files cleared.")
    logger.info("Output files cleared.")
    
def log_api_error(job, message):
    with job.error_file_lock:  # Make sure this is used
        with open(job.api_error_log_file, 'a') as f:
            f.write(f"{message}\n")

def log_script_error(job, message):
    with job.script_error_lock:  # Make sure this is used
        with open(job.script_error_log_file, 'a') as f:
            f.write(f"{message}\n")

def update_progress(job):
    with job.progress_lock:
        job.progress_done += 1
        job.cases_processed += 1
        # Calculate percentage here if needed with the lock held
        percentage = (job.progress_done / job.progress_total) * 100 if job.progress_total > 0 else 0
    
    # Update UI or log progress (can be outside the lock)
    # ...

def parse_input_file(file_name):
    import os, json
    cases = []
    _, ext = os.path.splitext(file_name)
    try:
        with open(file_name, 'r', encoding='latin-1') as file:
            for line in file:
                line = line.strip()
                if not line:
                    continue
                if ext.lower() == ".txt":
                    case_number = line
                    cases.append((case_number, line))
                else:
                    try:
                        data = json.loads(line)
                        case_number = data.get("Incidents_IncidentId", "").strip()
                        if case_number:
                            cases.append((case_number, line))
                        else:
                            log_script_error(None, f"No case number found in line: {line}")
                    except json.JSONDecodeError as e:
                        log_script_error(None, f"Invalid JSON format in line: {line}. Error: {e}")
    except IOError as e:
        log_script_error(None, f"Error reading file {file_name}: {e}")
    return cases

# --- Revised Error Logging ---
def log_and_write_error(job, case_number, original_data, error_message):
    log_api_error(job, error_message)
    append_processing_detail(job, f"Case {case_number}: Error logged.")
    update_progress(job)
    update_processed_cases(job, case_number)

# --- API Call Function (Non-job version remains unchanged) ---
def call_experiment_api(case_number, original_data):
    with config.token_lock:
        token = config.access_token
    if not token:
        log_api_error(None, "No access token available.")
        update_progress(None)
        return

    headers = {
        'Authorization': f'Bearer {token}',
        'Content-Type': 'application/json',
        'Accept': 'application/json'
    }
    run_model = {
        "DataSearchOptions": {
            "Search": case_number,
            "SearchMode": "any"
        },
        "MaxNumberOfRows": 5000
    }
    max_retries = 3
    attempt = 0
    success = False
    response = None
    while attempt < max_retries and not success:
        try:
            response = requests.post(f'{config.apiUrl}experiment/{job.experimentId}', headers=headers, data=json.dumps(run_model), timeout=config.API_TIMEOUT)
            if response.status_code == 200:
                success = True
                break
            elif response.status_code == 401:
                error_message = f"Error 401: {response.text} for case {case_number}"
                append_processing_detail(None, f"Case {case_number}: Received 401 error. Retrying in 5 seconds (attempt {attempt+1}/{max_retries}).")
                time.sleep(5)
            elif response.status_code == 400:
                error_message = f"Error 400: {response.text} for case {case_number}"
                log_and_write_error(None, case_number, original_data, error_message)
                return
            elif response.status_code == 429:
                match = re.search(r"Try again in (\d+) seconds", response.text)
                wait_time = int(match.group(1)) if match else 60
                new_wait = wait_time * 2
                append_processing_detail(None, f"Case {case_number}: Received 429. Retrying in {new_wait} seconds (attempt {attempt+1}/{max_retries}).")
                time.sleep(new_wait)
            elif response.status_code in [500, 502]:
                append_processing_detail(None, f"Case {case_number}: Received {response.status_code}. Retrying in 5 seconds (attempt {attempt+1}/{max_retries}).")
                time.sleep(5)
            else:
                error_message = f"Error {response.status_code}: {response.text} for case {case_number}"
                log_and_write_error(None, case_number, original_data, error_message)
                return
        except requests.exceptions.Timeout as te:
            append_processing_detail(None, f"Case {case_number}: Timeout occurred: {te}. Retrying in 5 seconds (attempt {attempt+1}/{max_retries}).")
            time.sleep(5)
        except Exception as e:
            append_processing_detail(None, f"Case {case_number}: Exception occurred: {e}. Retrying in 5 seconds (attempt {attempt+1}/{max_retries}).")
            time.sleep(5)
        attempt += 1

    if not success:
        if response is not None and response.status_code == 401:
            error_message = f"Error 401: {response.text} for case {case_number} after {max_retries} attempts."
        elif response is not None:
            error_message = f"Error {response.status_code}: {response.text} for case {case_number} after {max_retries} attempts."
        else:
            error_message = f"Failed to get a successful response for case {case_number} after {max_retries} attempts."
        log_and_write_error(None, case_number, original_data, error_message)
        return

    try:
        response_content = response.json()
        content_to_write = (response_content["chatHistory"]["messages"][-1]["content"]).replace("\\n", "\n")
        if not content_to_write:
            raise ValueError(f"No content found in API response for case {case_number}.")
        with open(config.RAW_OUTPUT_FILE, 'a') as file:
            file.write(content_to_write)
        csv_reader = csv.reader(content_to_write.splitlines())
        rows = list(csv_reader)
        if not rows:
            raise ValueError(f"No CSV rows found in API response for case {case_number}.")
        if config.api_header is None:
            config.api_header = rows[0]
            with open(config.API_RESPONSE_FILE, 'a', newline='') as file:
                writer = csv.writer(file, quoting=csv.QUOTE_ALL)
                writer.writerow(config.api_header)
        with open(config.API_RESPONSE_FILE, 'a', newline='') as file:
            writer = csv.writer(file, quoting=csv.QUOTE_ALL)
            for row in rows[1:]:
                writer.writerow(row)
        append_processing_detail(None, f"Output written for case {case_number}.")
        update_progress(None)
        update_processed_cases(None, case_number)
    except Exception as e:
        log_and_write_error(None, case_number, original_data, f"Exception while processing case {case_number}: {e}")

# --- Batch Processing ---
def process_batch(batch):
    for case_number, original_data in batch:
        call_experiment_api(case_number, original_data)

# --- Main Processing Loop (Non-job mode) ---
def processing_main():
    from config import generate_filename
    config.PROCESSED_TRACKING_FILE = generate_filename(config.ARGS.file, config.experimentId, "processed", "txt")
    config.API_401_ERROR_TRACKING_FILE = generate_filename(config.ARGS.file, config.experimentId, "401", "txt")

    if not config.resume_mode:
        if os.path.exists(config.PROCESSED_TRACKING_FILE):
            os.remove(config.PROCESSED_TRACKING_FILE)
        clear_output_files(None)
        clear_401_tracking_file(None)
    else:
        append_processing_detail(None, "Resuming processing using previous outputs.")

    file_name = config.ARGS.file
    use_threading = config.ARGS.threads > 0
    max_threads = config.ARGS.threads if use_threading else None
    batching = config.ARGS.batch > 0
    batch_size = config.ARGS.batch if batching else None

    cases = parse_input_file(file_name)
    if config.resume_mode:
        processed = load_processed_cases(None)
        cases = [case for case in cases if case[0] not in processed]
        if config.retry_401_flag:
            with open(config.API_401_ERROR_TRACKING_FILE, 'r') as f:
                retry_cases_set = set(line.strip() for line in f if line.strip())
            all_cases = parse_input_file(file_name)
            retry_cases = [case for case in all_cases if case[0] in retry_cases_set]
            cases = retry_cases + cases
    if not cases:
        print("No valid cases found or all cases have been processed in the input file.")
        sys.exit(1)

    config.total_cases = len(cases)
    config.cases_processed = 0

    stop_event = threading.Event()
    token_thread = threading.Thread(target=refresh_token, args=(stop_event,), daemon=True)
    token_thread.start()

    while config.access_token is None:
        time.sleep(1)

    if use_threading and batching:
        total_batches = (len(cases) + batch_size - 1) // batch_size
        #append_processing_detail(None, f"Processing {len(cases)} cases in {total_batches} batches of size {batch_size}.")
        append_processing_detail(None,f"Processing {len(cases)} cases using {max_threads} threads with efficient grouping " +
                f"(group size: {batch_size}, {total_batches} groups)")
        # This mode creates one thread per group of cases, rather than one thread per case
        # Each case still gets its own API call, but thread management is more efficient
        q = Queue()
        for i in range(0, len(cases), batch_size):
            q.put(cases[i:i + batch_size])
        sem = Semaphore(max_threads)
        thread_list = []
        while not q.empty():
            batch_group = q.get()
            sem.acquire()
            t = threading.Thread(target=lambda b=batch_group: (process_batch(b), sem.release()))
            thread_list.append(t)
            t.start()
        for t in thread_list:
            t.join()
    elif use_threading:
        sem = Semaphore(max_threads)
        thread_list = []
        append_processing_detail(None, f"Processing {len(cases)} cases with individual threads max of {max_threads} threads.")
        for case_number, original_data in cases:
            sem.acquire()
            t = threading.Thread(target=lambda c=case_number, d=original_data: (call_experiment_api(c, d), sem.release()))
            thread_list.append(t)
            t.start()
        for t in thread_list:
            t.join()
    elif batching:
        total_batches = (len(cases) + batch_size - 1) // batch_size
        append_processing_detail(None, f"Processing {len(cases)} cases in {total_batches} sequential groups " +  f"(group size: {batch_size})")
        for i in range(0, len(cases), batch_size):
            process_batch(cases[i:i + batch_size])
    else:
        append_processing_detail(None, f"Processing {len(cases)} cases in sequential mode.")
        for case_number, original_data in cases:
            call_experiment_api(case_number, original_data)

    append_processing_detail(None, "Processing complete.")
    print("Processing complete.")
    stop_event.set()
    token_thread.join()

# --- Job-Specific Processing Loop ---
def processing_main_job(job):
    # Ensure threads and batch_size have defaults if not present
    if not hasattr(job, 'threads'):
        job.threads = 0
    if not hasattr(job, 'batch_size'):
        job.batch_size = 0
        
    # ——— ISOLATE PER-JOB STATE ———
    job.api_header = None
    job.processing_details = []
    # Redirect global file paths to the job's own paths:
    config.PROCESSED_TRACKING_FILE   = job.processed_tracking_file
    config.API_401_ERROR_TRACKING_FILE = job.api_401_tracking_file
    config.RAW_OUTPUT_FILE           = job.raw_output_file
    config.API_RESPONSE_FILE         = job.api_response_file
    config.API_ERROR_LOG_FILE        = job.api_error_log_file
    config.SCRIPT_ERROR_LOG_FILE     = job.script_error_log_file
    if not job.resume_mode:
        if os.path.exists(job.processed_tracking_file):
            os.remove(job.processed_tracking_file)
        for file_path in [job.raw_output_file, job.api_response_file, job.api_error_log_file, job.script_error_log_file, job.api_401_tracking_file]:
            with open(file_path, 'w') as f:
                f.write("")
    else:
        job.log("Resuming processing using previous outputs.")
    
    file_name = job.input_file
    # Use job-specific threading and batching settings instead of global config
    use_threading = job.threads > 0
    max_threads = job.threads if use_threading else None
    batching = job.batch_size > 0
    batch_size = job.batch_size if batching else None

    cases = parse_input_file(file_name)
    if job.resume_mode:
        processed = load_processed_cases(job)
        remaining_cases = [case for case in cases if case[0] not in processed]
        # Preserve original total: if not already stored, save it now.
        if not hasattr(job, "initial_total") or job.initial_total == 0:
            job.initial_total = len(cases)
        job.progress_total = job.initial_total
        # Do not reset progress_done; it should reflect already processed cases.
        cases = remaining_cases
    else:
        job.progress_total = len(cases)
        job.progress_done = 0
        job.initial_total = len(cases)
        
    if not cases:
        job.log("No valid cases found or all cases have been processed in the input file.")
        return
    
    stop_event = threading.Event()
    token_thread = threading.Thread(target=refresh_token, args=(stop_event,), daemon=True)
    token_thread.start()

    while config.access_token is None:
        if job.cancel_event.is_set():
            job.log("Job cancelled while waiting for token.")
            stop_event.set()
            token_thread.join()
            return
        time.sleep(1)

    if use_threading and batching:
        total_batches = (len(cases) + batch_size - 1) // batch_size
        job.log(f"Processing {len(cases)} cases in {total_batches} batches of size {batch_size} using {max_threads} threads in parallel.")
        q = Queue()
        for i in range(0, len(cases), batch_size):
            q.put(cases[i:i + batch_size])
        sem = Semaphore(max_threads)
        thread_list = []
        while not q.empty():
            if job.cancel_event.is_set():
                job.log("Job cancellation requested during batching.")
                break
            batch_group = q.get()
            sem.acquire()
            t = threading.Thread(target=lambda b=batch_group: (process_batch_job(job, b), sem.release()))
            thread_list.append(t)
            t.start()
        for t in thread_list:
            t.join()
    elif use_threading:
        sem = Semaphore(max_threads)
        thread_list = []
        job.log(f"Processing {len(cases)} cases in threading mode with a maximum of {max_threads} threads.")
        for case_number, original_data in cases:
            if job.cancel_event.is_set():
                job.log("Job cancellation requested during threading mode.")
                break
            sem.acquire()
            t = threading.Thread(target=lambda c=case_number, d=original_data: (call_experiment_api_job(job, c, d), sem.release()))
            thread_list.append(t)
            t.start()
        for t in thread_list:
            t.join()
    elif batching:
        total_batches = (len(cases) + batch_size - 1) // batch_size
        job.log(f"Processing {len(cases)} cases in {total_batches} batches of size {batch_size}.")
        for i in range(0, len(cases), batch_size):
            if job.cancel_event.is_set():
                job.log("Job cancellation requested during batching sequential mode.")
                break
            process_batch_job(job, cases[i:i + batch_size])
    else:
        job.log(f"Processing {len(cases)} cases in sequential mode.")
        for case_number, original_data in cases:
            if job.cancel_event.is_set():
                job.log("Job cancellation requested in sequential mode.")
                break
            call_experiment_api_job(job, case_number, original_data)

    job.log("Processing complete.")
    print("Processing complete.")
    stop_event.set()
    token_thread.join()

def process_batch_job(job, batch):
    """Process a group of cases sequentially.
    
    This function processes each case in the group with its own individual API call.
    The grouping is for thread management efficiency, not for sending multiple cases
    in a single API call.
    """
    for case_number, original_data in batch:
        if job.cancel_event.is_set():
            job.log("Job cancellation requested inside group.")
            break
        call_experiment_api_job(job, case_number, original_data)

def call_experiment_api_job(job, case_number, original_data):
    if job.cancel_event.is_set():
        job.log(f"Skipping case {case_number} due to cancellation.")
        return

    with config.token_lock:
        token = config.access_token
    if not token:
        job.log("No access token available.")
        update_progress(job)
        update_processed_cases(job, case_number)
        return

    headers = {
        'Authorization': f'Bearer {token}',
        'Content-Type': 'application/json',
        'Accept': 'application/json'
    }
    run_model = {
        "DataSearchOptions": {
            "Search": "",
            "SearchMode": "any",
            "Filter": f"(IsEUSchrems eq false) and (CaseNumber eq '{case_number}')"
        },
        "MaxNumberOfRows": 5000
    }
    
    max_retries = 3
    attempt = 0
    success = False
    response = None
    error_message = None
    content_to_write = None

    while attempt < max_retries and not success:
        if job.cancel_event.is_set():
            job.log(f"Job cancelled during API call for case {case_number}.")
            return
        try:
            response = requests.post(
                f'{config.apiUrl}experiment/{job.experiment_id}',
                headers=headers, data=json.dumps(run_model),
                timeout=config.API_TIMEOUT
            )
            logger.debug(f"Raw API response for case {case_number} (attempt {attempt+1}): {response.text}")            
            if response.status_code == 200:
                success = True
                break
            elif response.status_code == 401:
                job.log(f"Case {case_number}: Received 401 error. Retrying in 5 seconds (attempt {attempt+1}/{max_retries}).")
                time.sleep(5)
            elif response.status_code == 400:
                error_message = f"Error 400: {response.text} for case {case_number}"
                break
            elif response.status_code == 429:
                match = re.search(r"Try again in (\d+) seconds", response.text)
                wait_time = int(match.group(1)) if match else 60
                new_wait = wait_time * 2
                job.log(f"Case {case_number}: Received 429. Retrying in {new_wait} seconds (attempt {attempt+1}/{max_retries}).")
                time.sleep(new_wait)
            elif response.status_code in [500, 502]:
                job.log(f"Case {case_number}: Received {response.status_code}. Retrying in 5 seconds (attempt {attempt+1}/{max_retries}).")
                time.sleep(5)
            else:
                error_message = f"Error {response.status_code}: {response.text} for case {case_number}"
                break
        except requests.exceptions.Timeout as te:
            job.log(f"Case {case_number}: Timeout occurred: {te}. Retrying in 5 seconds (attempt {attempt+1}/{max_retries}).")
            time.sleep(5)
        except Exception as e:
            job.log(f"Case {case_number}: Exception occurred: {e}. Retrying in 5 seconds (attempt {attempt+1}/{max_retries}).")
            time.sleep(5)
        attempt += 1

    if not success:
        if not error_message:
            if response is not None and response.status_code == 401:
                error_message = f"Error 401: {response.text} for case {case_number} after {max_retries} attempts."
                update_401_error(job, case_number, error_message)
            elif response is not None:
                error_message = f"Error {response.status_code}: {response.text} for case {case_number} after {max_retries} attempts."
            else:
                error_message = f"Failed to get a successful response for case {case_number} after {max_retries} attempts."
        log_api_error(job, error_message)
    else:
        try:
            response_content = response.json()
            if job.parsing_method.upper() == "JSON":
                content_to_write = json.dumps(response_content, indent=2)
            else:
                # Check if the expected keys exist
                if ("chatHistory" in response_content and 
                    "messages" in response_content["chatHistory"] and 
                    len(response_content["chatHistory"]["messages"]) > 0):
                    # Use the last message's content
                    content_raw = response_content["chatHistory"]["messages"][-1].get("content")
                    if content_raw is None:
                        raise ValueError("Expected 'content' key is missing in the last message.")
                    content_to_write = content_raw.replace("\\n", "\n")
                else:
                    raise ValueError("The API response does not contain the expected chatHistory/messages structure.")
            
            if not content_to_write:
                raise ValueError(f"No content found in API response for case {case_number}.")
        except Exception as e:
            error_message = f"Exception while processing case {case_number}: {e}"
            job.log(error_message)
            log_api_error(job, error_message)
#        try:
#            response_content = response.json()
#            if job.parsing_method.upper() == "JSON":
#                content_to_write = json.dumps(response_content, indent=2)
#            else:
#                content_to_write = (response_content["chatHistory"]["messages"][-1]["content"]).replace("\\n", "\n")
#            if not content_to_write:
#                raise ValueError(f"No content found in API response for case {case_number}.")
#        except Exception as e:
#            error_message = f"Exception while processing case {case_number}: {e}"
#            job.log(error_message)
#            log_api_error(job, error_message)

    if job.parsing_method.upper() == "JSON":
        from consolidation import consolidate_case_txt
        consolidate_case_txt(
            job=job,
            case_number=case_number,
            original_line=original_data,
            api_output=content_to_write,
            error_message=error_message
        )
        if success and content_to_write:
            job.log(f"Output written for case {case_number}.")    
    elif job.parsing_method.upper() == "TXT":
        from consolidation import consolidate_case_txt
        consolidate_case_txt(
            job=job,
            case_number=case_number,
            original_line=original_data,
            api_output=content_to_write,
            error_message=error_message
        )
        if success and content_to_write:
            job.log(f"Output written for case {case_number}.")
    elif success and job.parsing_method.upper() == "CSV":
        try:
            with open(job.raw_output_file, 'a') as file:
                file.write(content_to_write)
            csv_reader = csv.reader(content_to_write.splitlines())
            rows = list(csv_reader)
            if not rows:
                raise ValueError(f"No CSV rows found in API response for case {case_number}.")
            if not os.path.exists(job.api_response_file) or os.stat(job.api_response_file).st_size == 0:
                with open(job.api_response_file, 'a', newline='') as file:
                    writer = csv.writer(file, quoting=csv.QUOTE_ALL)
                    writer.writerow(rows[0])
            with open(job.api_response_file, 'a', newline='') as file:
                writer = csv.writer(file, quoting=csv.QUOTE_ALL)
                for row in rows[1:]:
                    writer.writerow(row)
            job.log(f"Output written for case {case_number}.")
        except Exception as e:
            job.log(f"Exception while processing case {case_number}: {e}")
            log_script_error(job, str(e))

    update_progress(job)
    update_processed_cases(job, case_number)

def write_raw_output(job, case_number, data):
    with job.raw_output_lock:
        with open(job.raw_output_file, 'a', encoding='utf-8') as f:
            f.write(f"Case {case_number}:\n")
            f.write(data)
            f.write("\n\n")
