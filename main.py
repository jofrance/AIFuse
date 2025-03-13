#!/usr/bin/env python3
import argparse
import sys
import os
import config
import auth
import processing
import consolidation
import utils
import curses

def validate_config():
    missing = []
    if not config.OUTPUT_DIR:
        missing.append("OUTPUT_DIR")
    if not config.default_consolidated_csv:
        missing.append("default_consolidated_csv")
    if not config.default_consolidated_excel:
        missing.append("default_consolidated_excel")
    if not config.RAW_OUTPUT_FILE:
        missing.append("RAW_OUTPUT_FILE")
    if not config.API_RESPONSE_FILE:
        missing.append("API_RESPONSE_FILE")
    if not config.API_ERROR_LOG_FILE:
        missing.append("API_ERROR_LOG_FILE")
    if not config.SCRIPT_ERROR_LOG_FILE:
        missing.append("SCRIPT_ERROR_LOG_FILE")
    if not config.PROCESSED_TRACKING_FILE:
        missing.append("PROCESSED_TRACKING_FILE")
    if not config.API_401_ERROR_TRACKING_FILE:
        missing.append("API_401_ERROR_TRACKING_FILE")
    if not config.apiUrl:
        missing.append("apiUrl")
    if not config.experimentId:
        missing.append("experimentId")
    if not config.API_TIMEOUT:
        missing.append("API_TIMEOUT")
    if not config.client_id:
        missing.append("client_id")
    if not config.authority:
        missing.append("authority")
    if not config.scopes:
        missing.append("scopes")		
    if missing:
        print(f"Configuration error: The following configuration values are missing or empty: {', '.join(missing)}")
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description="Integrated API processing and consolidation tool")
    parser.add_argument("input", help="Input JSON file with one case per line")
    parser.add_argument("-t", "--threads", type=int, default=0,
                        help="Maximum number of threads for API processing (0 for sequential)")
    parser.add_argument("-b", "--batch", type=int, default=0,
                        help="Batch size for processing (0 means no batching)")
    parser.add_argument("--consolidated-csv", default=config.default_consolidated_csv,
                        help="Output consolidated CSV file")
    parser.add_argument("--consolidated-excel", default=config.default_consolidated_excel,
                        help="Output consolidated Excel file")
    parser.add_argument("--no-ui", action="store_true",
                        help="Disable curses UI and run processing in plain console mode")
    config.ARGS = parser.parse_args()

    # Processing Phase
    if config.ARGS.no_ui:
        processing.processing_main()
    else:
        curses.wrapper(processing.curses_main)

    # Consolidation Phase
    print("\nStarting consolidation phase...")
    original_file = config.ARGS.input
    original_cases = consolidation.load_original_cases(original_file)
    print(f"Loaded {len(original_cases)} original cases.")
    error_log = consolidation.load_error_log(config.API_ERROR_LOG_FILE)
    print(f"Loaded {len(error_log)} error entries.")
    api_hdr, api_dict = consolidation.load_api_responses(config.API_RESPONSE_FILE)
    if api_hdr:
        print(f"API header found: {api_hdr}")
    else:
        print("No API header found; using default placeholder.")
    total_api_rows = sum(len(v) for v in api_dict.values())
    print(f"Loaded {total_api_rows} API response entries.")
    consolidation.consolidate_data(original_file, original_cases, error_log, api_hdr, api_dict, config.default_consolidated_csv)
    utils.write_csv_to_excel(config.default_consolidated_csv, config.default_consolidated_excel)
    print("Consolidation phase complete.")

if __name__ == "__main__":
    validate_config()
    main()

