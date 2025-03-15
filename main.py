#!/usr/bin/env python3
import argparse
import sys
import os
import platform
import config
import auth
import processing
import consolidation
import utils

def validate_config():
    missing = []
    if not config.OUTPUT_DIR:
        missing.append("OUTPUT_DIR")
    if not os.path.basename(config.default_consolidated_csv):
        missing.append("default_consolidated_csv")
    if not os.path.basename(config.default_consolidated_excel):
        missing.append("default_consolidated_excel")
    if not os.path.basename(config.RAW_OUTPUT_FILE):
        missing.append("RAW_OUTPUT_FILE")
    if not os.path.basename(config.API_RESPONSE_FILE):
        missing.append("API_RESPONSE_FILE")
    if not os.path.basename(config.API_ERROR_LOG_FILE):
        missing.append("API_ERROR_LOG_FILE")
    if not os.path.basename(config.SCRIPT_ERROR_LOG_FILE):
        missing.append("SCRIPT_ERROR_LOG_FILE")
    if not os.path.basename(config.PROCESSED_TRACKING_FILE):
        missing.append("PROCESSED_TRACKING_FILE")
    if not os.path.basename(config.API_401_ERROR_TRACKING_FILE):
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
    # Set up argument parsing with input file optional via -f/--file.
    parser = argparse.ArgumentParser(description="Integrated API processing and consolidation tool")
    parser.add_argument("-f", "--file", default="",
                        help="Input JSON file with one case per line")
    parser.add_argument("-t", "--threads", type=int, default=0,
                        help="Maximum number of threads for API processing (0 for sequential)")
    parser.add_argument("-b", "--batch", type=int, default=0,
                        help="Batch size for processing (0 means no batching)")
    parser.add_argument("--consolidated-csv", default=config.default_consolidated_csv,
                        help="Output consolidated CSV file")
    parser.add_argument("--consolidated-excel", default=config.default_consolidated_excel,
                        help="Output consolidated Excel file")
    parser.add_argument("--no-ui", action="store_true",
                        help="Disable UI and run processing in plain console mode")
    parser.add_argument("--with-curses", action="store_true",
                        help="Force using curses UI even on Windows")
    config.ARGS = parser.parse_args()

    # If no input file is provided...
    if not config.ARGS.file.strip():
        # For console/no-ui or curses mode (or non-Windows), prompt via console.
        if config.ARGS.no_ui or config.ARGS.with_curses or platform.system() != "Windows":
            config.ARGS.file = input("Please enter the path to the input JSON file: ").strip()
            if not config.ARGS.file:
                print("No input file provided. Exiting.")
                sys.exit(1)
        # For Windows UI mode, win_ui.py will handle file selection.

    # Now choose which UI to launch.
    if config.ARGS.no_ui:
        processing.processing_main()
    elif config.ARGS.with_curses:
        try:
            import curses
            curses.wrapper(processing.curses_main)
        except Exception as e:
            print(f"Curses UI error: {e}")
            print("Falling back to plain console mode.")
            processing.processing_main()
    else:
        system = platform.system()
        if system == "Windows":
            try:
                from win_ui import tk_ui_main
                tk_ui_main()
            except Exception as e:
                print(f"Error launching Tkinter UI: {e}")
                print("Falling back to curses UI on Windows.")
                try:
                    import curses
                    curses.wrapper(processing.curses_main)
                except Exception as e:
                    print(f"Curses UI error: {e}")
                    print("Falling back to plain console mode.")
                    processing.processing_main()
        else:
            try:
                import curses
                curses.wrapper(processing.curses_main)
            except Exception as e:
                print(f"Curses UI error: {e}")
                print("Falling back to plain console mode.")
                processing.processing_main()

    # Consolidation Phase (runs after UI completes).
    print("\nStarting consolidation phase...")
    original_file = config.ARGS.file
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
