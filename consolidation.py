import os
import csv
import json
import re
import pandas as pd
from openpyxl.styles import Alignment
import config
from log_config import logger

def load_original_cases(file_name):
    cases = {}
    ext = os.path.splitext(file_name)[1].lower()
    with open(file_name, 'r', encoding='latin-1') as f:
        for line in f:
            line = line.strip()
            if line:
                if ext == ".txt":
                    # For text files, assume each line is the case number.
                    case_num = line
                    # Create a minimal data structure for compatibility.
                    cases[case_num] = {"Incidents_IncidentId": case_num, "raw": line}
                else:
                    try:
                        data = json.loads(line)
                        case_num = data.get("Incidents_IncidentId", "").strip()
                        if case_num:
                            cases[case_num] = data
                        else:
                            print(f"Warning: No case number found in line: {line}")
                            logger.info("Warning: No case number found in line: {line}")
                    except json.JSONDecodeError as e:
                        print(f"Warning: Invalid JSON line: {line} Error: {e}")
                        logger.info("Warning: Invalid JSON line: {line} Error: {e}")
    return cases

def load_error_log(file_name):
    errors = {}
    if os.path.exists(file_name):
        with open(file_name, 'r', encoding='latin-1') as f:
            for line in f:
                line = line.strip()
                if line:
                    m = re.search(r'for case (\S+)', line)
                    if m:
                        case_num = m.group(1)
                        errors[case_num] = line
                    else:
                        print(f"Warning: Could not extract case number from error: {line}")
    return errors

def load_api_responses(file_name):
    if not os.path.exists(file_name) or os.stat(file_name).st_size == 0:
        # No responses to load — return empty header + dict
        return None, {}
    responses = {}
    candidates = []  # list of tuples: (row, column_count)
    if os.path.exists(file_name):
        with open(file_name, 'r', newline='', encoding='latin-1') as f:
            lines = f.readlines()
        import csv
        for line in lines:
            stripped = line.strip()
            if not stripped.startswith('"'):
                continue
            try:
                row = next(csv.reader([stripped], quotechar='"', delimiter=','))
            except Exception:
                continue
            if len(row) < 2:
                continue
            candidates.append((row, len(row)))
        if not candidates:
            print("Warning: No valid CSV candidates found in API response file.")
            return None, responses
        count_freq = {}
        for _, col_count in candidates:
            count_freq[col_count] = count_freq.get(col_count, 0) + 1
        most_common_count = max(count_freq, key=count_freq.get)
        header = None
        valid_rows = []
        for row, col_count in candidates:
            if col_count == most_common_count:
                if header is None:
                    header = row
                else:
                    if row == header:
                        continue
                    valid_rows.append(row)
        if header is None:
            print("Warning: No valid CSV header found in API response file.")
            return None, responses
        for row in valid_rows:
            case_number = row[0]
            if case_number in responses:
                responses[case_number].append(row)
            else:
                responses[case_number] = [row]
        return header, responses
    else:
        print(f"File {file_name} not found.")
        return None, responses

def consolidate_data(original_file, original_cases, error_log, api_header, api_dict, output_csv):
    consolidated_rows = []
    json_keys = set()
    for data in original_cases.values():
        json_keys.update(data.keys())
    json_keys = sorted(json_keys)
    if api_header is None:
        api_header = ["API_Column"]
    consolidated_header = api_header + json_keys + ["Error_Message"]
    consolidated_rows.append(consolidated_header)
    with open(original_file, 'r', encoding='latin-1') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                continue
            case_num = data.get("Incidents_IncidentId", "").strip()
            json_values = [data.get(key, "") for key in json_keys]
            if case_num in error_log:
                placeholders = ["Information not found"] * len(api_header)
                error_msg = error_log[case_num]
                row = placeholders + json_values + [error_msg]
                consolidated_rows.append(row)
            else:
                if case_num in api_dict:
                    for api_row in api_dict[case_num]:
                        row = api_row + json_values + [""]
                        consolidated_rows.append(row)
                else:
                    row = ["Missing"] * len(api_header) + json_values + [""]
                    consolidated_rows.append(row)
    with open(output_csv, 'w', newline='', encoding='latin-1') as f:
        writer = csv.writer(f, quoting=csv.QUOTE_ALL)
        writer.writerows(consolidated_rows)
    print(f"Consolidated CSV written to {output_csv}")

def load_original_cases_txt(input_file):
    """
    Load original cases from the input file.
    Returns a dictionary mapping case numbers to their JSON objects.
    """
    cases = {}
    with open(input_file, 'r', encoding='latin-1') as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    data = json.loads(line)
                    case_num = data.get("Incidents_IncidentId", "").strip()
                    if case_num:
                        cases[case_num] = data
                except json.JSONDecodeError as e:
                    logger.info(f"Invalid JSON line: {line} Error: {e}")
    return cases

def load_error_log_txt(error_log_file):
    """
    Loads error log into a dictionary keyed by case number.
    Assumes each error line contains 'for case <case_number>'.
    """
    errors = {}
    if os.path.exists(error_log_file):
        with open(error_log_file, 'r', encoding='latin-1') as f:
            for line in f:
                line = line.strip()
                if line:
                    m = re.search(r'for case (\S+)', line)
                    if m:
                        case_num = m.group(1)
                        errors[case_num] = line
                    else:
                        logger.info(f"Could not extract case number from error: {line}")
    return errors

def load_api_responses_txt(api_response_file):
    """
    Loads API responses for TXT consolidation.
    Assumes that the file contains blocks delimited by a line with "-----"
    and that each block starts with "Case <case_number>:".
    Returns a dictionary mapping case numbers to the entire block.
    """
    responses = {}
    if os.path.exists(api_response_file):
        with open(api_response_file, 'r', encoding='latin-1') as f:
            content = f.read()
        # Split blocks on a line that contains only hyphens
        blocks = re.split(r'\n*-info\ note*\n', content)
        for block in blocks:
            block = block.strip()
            if block:
                # The first line should be like "Case 123:"
                first_line = block.splitlines()[0]
                m = re.match(r'Case\s+(\S+):', first_line)
                if m:
                    case_num = m.group(1)
                    responses[case_num] = block
                else:
                    logger.info(f"Block does not start with case header: {block}")
    return responses

def simple_txt_consolidator(input_file, error_log_file, api_response_file, output_txt):
    """
    Consolidate TXT parsing:
      - For each case in the original input file,
      - Write a block:
          Case <case_number>:
          <API response block or error message>
          ----------------------------------------------
    """
    original = load_original_cases_txt(input_file)
    errors = load_error_log_txt(error_log_file)
    responses = load_api_responses_txt(api_response_file)

    with open(output_txt, 'w', encoding='latin-1') as out:
        for case_num in original:
            out.write(f"Case {case_num}:\n")
            if case_num in responses:
                out.write(responses[case_num] + "\n")
            elif case_num in errors:
                out.write(errors[case_num] + "\n")
            else:
                out.write("No API response or error found.\n")
            out.write("\n" + "-"*50 + "\n\n")
    print(f"TXT consolidation written to {output_txt}")

def consolidate_case_txt(job, case_number, original_line, api_output, error_message):
    print(f"[DEBUG] Writing TXT consolidation for case {case_number} to file: {job.consolidated_txt}")
    """
    Immediately consolidates a single case for TXT mode.
    Writes a block containing:
      - The case header,
      - Original case data (pretty-printed if possible),
      - Either the API response (if available) or the error message,
      - A separator line.
    """
    try:
        original_data = json.loads(original_line)
        original_str = json.dumps(original_data, indent=2)
    except Exception as e:
        logger.info(f"Error parsing original data for case {case_number}: {e}")
        original_str = original_line

    block = f"Case {case_number}:\n"
    block += "Original Data:\n" + original_str + "\n\n"
    if api_output:
        block += "API Response:\n" + api_output + "\n"
    elif error_message:
        block += "Error:\n" + error_message + "\n"
    else:
        block += "No API response or error found.\n"
    block += "\n" + "-" * 50 + "\n\n"

    # Write the block with thread safety.
    with job.consolidation_lock:
        with open(job.consolidated_txt, 'a', encoding='latin-1') as f:
            f.write(block)


