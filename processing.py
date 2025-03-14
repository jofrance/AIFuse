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

import config
from auth import get_access_token, refresh_token

# --- Tracking File Functions ---
def load_processed_cases():
    processed = set()
    if os.path.exists(config.PROCESSED_TRACKING_FILE):
        with open(config.PROCESSED_TRACKING_FILE, 'r') as f:
            for line in f:
                processed.add(line.strip())
    return processed

def update_processed_cases(case_number):
    with open(config.PROCESSED_TRACKING_FILE, 'a') as f:
        f.write(str(case_number) + "\n")

def load_401_errors():
    errors = set()
    if os.path.exists(config.API_401_ERROR_TRACKING_FILE):
        with open(config.API_401_ERROR_TRACKING_FILE, 'r') as f:
            for line in f:
                case = line.strip()
                if case:
                    errors.add(case)
    return errors

def update_401_error(case_number, error_message):
    with open(config.API_401_ERROR_TRACKING_FILE, 'a') as f:
        f.write(str(case_number) + "\n")
    append_processing_detail(f"Case {case_number}: 401 error logged.")

def clear_401_tracking_file():
    if os.path.exists(config.API_401_ERROR_TRACKING_FILE):
        with open(config.API_401_ERROR_TRACKING_FILE, 'w') as f:
            f.write("")

# --- Curses Prompt for Resume/Start Fresh ---
def check_resume_option(stdscr):
    if os.path.exists(config.PROCESSED_TRACKING_FILE):
        stdscr.clear()
        stdscr.addstr(0, 0, "Previous run detected.")
        processed = load_processed_cases()
        try:
            with open(config.ARGS.input, 'r') as f:
                total_input = sum(1 for line in f if line.strip())
        except Exception:
            total_input = "unknown"
        stdscr.addstr(1, 0, f"Processed cases: {len(processed)}. Total input cases: {total_input}.")
        stdscr.addstr(2, 0, "Press 'R' to resume processing remaining cases, or 'S' to start fresh:")
        stdscr.refresh()
        while True:
            key = stdscr.getch()
            if key in (ord('r'), ord('R')):
                config.resume_mode = True
                break
            elif key in (ord('s'), ord('S')):
                config.resume_mode = False
                break
        stdscr.addstr(3, 0, f"User selected: {'RESUME' if config.resume_mode else 'START FRESH'}.")
        stdscr.refresh()
        time.sleep(2)
        if config.resume_mode and os.path.exists(config.API_401_ERROR_TRACKING_FILE):
            with open(config.API_401_ERROR_TRACKING_FILE, 'r') as f:
                retry_lines = [line.strip() for line in f if line.strip()]
            if retry_lines:
                stdscr.addstr(4, 0, f"There are {len(retry_lines)} cases with persistent 401 errors.")
                stdscr.addstr(5, 0, "Press 'R' to retry these 401 errors, or 'S' to skip them:")
                stdscr.refresh()
                while True:
                    key = stdscr.getch()
                    if key in (ord('r'), ord('R')):
                        config.retry_401_flag = True
                        break
                    elif key in (ord('s'), ord('S')):
                        config.retry_401_flag = False
                        break
                stdscr.addstr(6, 0, f"User selected: {'Retry 401 errors' if config.retry_401_flag else 'Skip 401 errors'}.")
                stdscr.refresh()
                time.sleep(2)
    else:
        config.resume_mode = False

# --- Logging and Progress Helpers ---
def append_processing_detail(message):
    with config.details_lock:
        config.processing_details.append(message)
        if len(config.processing_details) > 20:
            config.processing_details.pop(0)
    #print(message)

def clear_output_files():
    output_files = [config.RAW_OUTPUT_FILE, config.API_RESPONSE_FILE, config.API_ERROR_LOG_FILE, config.SCRIPT_ERROR_LOG_FILE, config.API_401_ERROR_TRACKING_FILE]
    for file_name in output_files:
        with open(file_name, 'w') as file:
            file.write("")
    append_processing_detail("Output files cleared.")
    print("Output files cleared.")

def log_api_error(message):
    with open(config.API_ERROR_LOG_FILE, 'a') as file:
        file.write(message + "\n")
    append_processing_detail(message)
    print(message, file=sys.stderr)

def log_script_error(message):
    with open(config.SCRIPT_ERROR_LOG_FILE, 'a') as file:
        file.write(message + "\n")
    append_processing_detail(message)
    print(message, file=sys.stderr)

def update_progress():
    with config.progress_lock:
        config.cases_processed += 1

# --- Input File Parsing ---
def parse_input_file(file_name):
    cases = []
    try:
        with open(file_name, 'r') as file:
            for line in file:
                line = line.strip()
                if line:
                    try:
                        data = json.loads(line)
                        case_number = data.get("Incidents_IncidentId", "").strip()
                        if case_number:
                            cases.append((case_number, line))
                        else:
                            log_script_error(f"No case number found in line: {line}")
                    except json.JSONDecodeError as e:
                        log_script_error(f"Invalid JSON format in line: {line}. Error: {e}")
    except IOError as e:
        log_script_error(f"Error reading file {file_name}: {e}")
    return cases

# --- Revised Error Logging ---
def log_and_write_error(case_number, original_data, error_message):
    log_api_error(error_message)
    append_processing_detail(f"Case {case_number}: Error logged.")
    update_progress()
    update_processed_cases(case_number)

# --- API Call Function ---
def call_experiment_api(case_number, original_data):
    with config.token_lock:
        token = config.access_token
    if not token:
        log_api_error("No access token available.")
        update_progress()
        update_processed_cases(case_number)
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
            response = requests.post(f'{config.apiUrl}experiment/{config.experimentId}', headers=headers, data=json.dumps(run_model), timeout=config.API_TIMEOUT)
            if response.status_code == 200:
                success = True
                break
            elif response.status_code == 401:
                error_message = f"Error 401: {response.text} for case {case_number}"
                append_processing_detail(f"Case {case_number}: Received 401 error. Retrying in 5 seconds (attempt {attempt+1}/{max_retries}).")
                time.sleep(5)
            elif response.status_code == 400:
                error_message = f"Error 400: {response.text} for case {case_number}"
                log_and_write_error(case_number, original_data, error_message)
                return
            elif response.status_code == 429:
                match = re.search(r"Try again in (\d+) seconds", response.text)
                wait_time = int(match.group(1)) if match else 60
                new_wait = wait_time * 2
                append_processing_detail(f"Case {case_number}: Received 429. Retrying in {new_wait} seconds (attempt {attempt+1}/{max_retries}).")
                time.sleep(new_wait)
            elif response.status_code in [500, 502]:
                append_processing_detail(f"Case {case_number}: Received {response.status_code}. Retrying in 5 seconds (attempt {attempt+1}/{max_retries}).")
                time.sleep(5)
            else:
                error_message = f"Error {response.status_code}: {response.text} for case {case_number}"
                log_and_write_error(case_number, original_data, error_message)
                return
        except requests.exceptions.Timeout as te:
            append_processing_detail(f"Case {case_number}: Timeout occurred: {te}. Retrying in 5 seconds (attempt {attempt+1}/{max_retries}).")
            time.sleep(5)
        except Exception as e:
            append_processing_detail(f"Case {case_number}: Exception occurred: {e}. Retrying in 5 seconds (attempt {attempt+1}/{max_retries}).")
            time.sleep(5)
        attempt += 1

    if not success:
        if response is not None and response.status_code == 401:
            error_message = f"Error 401: {response.text} for case {case_number} after {max_retries} attempts."
            update_401_error(case_number, error_message)
        else:
            if response is not None:
                error_message = f"Error {response.status_code}: {response.text} for case {case_number} after {max_retries} attempts."
            else:
                error_message = f"Failed to get a successful response for case {case_number} after {max_retries} attempts."
        log_and_write_error(case_number, original_data, error_message)
        return

    try:
        response_content = response.json()
        content_to_write = (response_content["chatHistory"]["messages"][1]["content"]).replace("\\n", "\n")
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
        append_processing_detail(f"Output written for case {case_number}.")
        #print(f"Output written for case {case_number}.")
        update_progress()
        update_processed_cases(case_number)
    except Exception as e:
        log_and_write_error(case_number, original_data, f"Exception while processing case {case_number}: {e}")

# --- Batch Processing ---
def process_batch(batch):
    for case_number, original_data in batch:
        call_experiment_api(case_number, original_data)

# --- Curses UI and Main Processing Loop ---
def processing_main():
    if not config.resume_mode:
        if os.path.exists(config.PROCESSED_TRACKING_FILE):
            os.remove(config.PROCESSED_TRACKING_FILE)
        clear_output_files()
        clear_401_tracking_file()
    else:
        append_processing_detail("Resuming processing using previous outputs.")

    file_name = config.ARGS.input
    use_threading = config.ARGS.threads > 0
    max_threads = config.ARGS.threads if use_threading else None
    batching = config.ARGS.batch > 0
    batch_size = config.ARGS.batch if batching else None

    cases = parse_input_file(file_name)
    if config.resume_mode:
        processed = load_processed_cases()
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
        append_processing_detail(f"Processing {len(cases)} cases in {total_batches} batches of size {batch_size}.")
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
        append_processing_detail(f"Processing {len(cases)} cases in threading mode with a maximum of {max_threads} threads.")
        for case_number, original_data in cases:
            sem.acquire()
            t = threading.Thread(target=lambda c=case_number, d=original_data: (call_experiment_api(c, d), sem.release()))
            thread_list.append(t)
            t.start()
        for t in thread_list:
            t.join()
    elif batching:
        total_batches = (len(cases) + batch_size - 1) // batch_size
        append_processing_detail(f"Processing {len(cases)} cases in {total_batches} batches of size {batch_size}.")
        for i in range(0, len(cases), batch_size):
            process_batch(cases[i:i + batch_size])
    else:
        append_processing_detail(f"Processing {len(cases)} cases in sequential mode.")
        for case_number, original_data in cases:
            call_experiment_api(case_number, original_data)

    append_processing_detail("Processing complete.")
    print("Processing complete.")
    stop_event.set()
    token_thread.join()

def curses_main(stdscr):
    curses.curs_set(0)
    stdscr.nodelay(True)
    spinner_cycle = itertools.cycle(["|", "/", "-", "\\"])
    start_time = time.time()

    check_resume_option(stdscr)
    processing_thread = threading.Thread(target=processing_main)
    processing_thread.start()

    while processing_thread.is_alive() or config.cases_processed < config.total_cases:
        elapsed_time = time.time() - start_time
        minutes, seconds = divmod(int(elapsed_time), 60)
        stdscr.move(0, 0)
        stdscr.clrtoeol()
        stdscr.addstr(0, 0, f"Processing cases: {config.cases_processed}/{config.total_cases}")
        stdscr.move(1, 0)
        stdscr.clrtoeol()
        stdscr.addstr(1, 0, f"{next(spinner_cycle)}")
        stdscr.move(2, 0)
        stdscr.clrtoeol()
        stdscr.addstr(2, 0, f"Elapsed time: {minutes:02}:{seconds:02}")
        with config.details_lock:
            details_to_show = config.processing_details[-20:]
        for i, msg in enumerate(details_to_show):
            stdscr.move(4 + i, 0)
            stdscr.clrtoeol()
            stdscr.addstr(4 + i, 0, msg[:curses.COLS - 1])
        stdscr.refresh()
        time.sleep(0.1)
    stdscr.nodelay(False)
    max_y, max_x = stdscr.getmaxyx()
    stdscr.move(max_y - 1, 0)
    stdscr.clrtoeol()
    stdscr.addstr(max_y - 1, 0, "Processing complete! Press Enter to exit.")
    stdscr.refresh()
    while True:
        key = stdscr.getch()
        if key in (10, 13):
            break
    processing_thread.join()

