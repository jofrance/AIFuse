import os
import csv
import json
import re
import pandas as pd
from openpyxl.styles import Alignment
import config

def load_original_cases(file_name):
    cases = {}
    with open(file_name, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    data = json.loads(line)
                    case_num = data.get("Incidents_IncidentId", "").strip()
                    if case_num:
                        cases[case_num] = data
                    else:
                        print(f"Warning: No case number found in line: {line}")
                except json.JSONDecodeError as e:
                    print(f"Warning: Invalid JSON line: {line} Error: {e}")
    return cases

def load_error_log(file_name):
    errors = {}
    if os.path.exists(file_name):
        with open(file_name, 'r', encoding='utf-8') as f:
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
    responses = {}
    candidates = []  # list of tuples: (row, column_count)
    if os.path.exists(file_name):
        with open(file_name, 'r', newline='', encoding='utf-8') as f:
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
    with open(original_file, 'r', encoding='utf-8') as f:
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
    with open(output_csv, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f, quoting=csv.QUOTE_ALL)
        writer.writerows(consolidated_rows)
    print(f"Consolidated CSV written to {output_csv}")

