import os
import sys
import threading
import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox
import config
import processing
import consolidation
import utils  # This module now contains the check_resume_status() function

def tk_check_resume_option(root):
    """
    Uses the shared check_resume_status() function from utils.py to determine if there is resume data.
    If the tracking file exists and contains processed cases:
       - If all cases are processed, informs the user and exits.
       - Otherwise, prompts the user to resume or start fresh.
    If the tracking file is missing or empty, sets resume_mode to False.
    """
    status = utils.check_resume_status()
    total_input = status["total_input"]
    processed_count = status["processed_count"]

    # Only consider prompting if the tracking file exists and has some processed cases.
    if os.path.exists(config.PROCESSED_TRACKING_FILE) and processed_count > 0:
        if processed_count >= total_input:
            messagebox.showinfo("All Cases Processed",
                                f"All {total_input} cases are already processed. Nothing to do.",
                                parent=root)
            root.destroy()
            sys.exit(0)
        else:
            msg = (f"Previous run detected.\nProcessed cases: {processed_count}\n"
                   f"Total input cases: {total_input}\n\n"
                   "Do you want to resume processing (Yes) or start fresh (No)?")
            result = messagebox.askyesno("Resume or Start Fresh", msg, parent=root)
            config.resume_mode = True if result else False

            # Check for persistent 401 errors if resuming.
            api401_file = os.path.abspath(config.API_401_ERROR_TRACKING_FILE)
            if config.resume_mode and os.path.exists(api401_file):
                with open(api401_file, 'r') as f:
                    retry_lines = [line.strip() for line in f if line.strip()]
                if retry_lines:
                    msg2 = (f"There are {len(retry_lines)} cases with persistent 401 errors.\n"
                            "Do you want to retry these errors (Yes) or skip them (No)?")
                    result2 = messagebox.askyesno("Retry 401 Errors", msg2, parent=root)
                    config.retry_401_flag = True if result2 else False
    else:
        # No tracking file or it's empty; no resume data.
        config.resume_mode = False


def run_consolidation_phase():
    config.processing_details.append("Starting consolidation phase...")
    original_file = config.ARGS.input
    original_cases = consolidation.load_original_cases(original_file)
    config.processing_details.append(f"Loaded {len(original_cases)} original cases.")
    error_log = consolidation.load_error_log(config.API_ERROR_LOG_FILE)
    config.processing_details.append(f"Loaded {len(error_log)} error entries.")
    api_hdr, api_dict = consolidation.load_api_responses(config.API_RESPONSE_FILE)
    if api_hdr:
        config.processing_details.append(f"API header found: {api_hdr}")
    else:
        config.processing_details.append("No API header found; using default placeholder.")
    total_api_rows = sum(len(v) for v in api_dict.values())
    config.processing_details.append(f"Loaded {total_api_rows} API response entries.")
    consolidation.consolidate_data(
        original_file, original_cases, error_log, api_hdr, api_dict, config.default_consolidated_csv
    )
    config.processing_details.append(f"Consolidated CSV written to {config.default_consolidated_csv}")
    utils.write_csv_to_excel(config.default_consolidated_csv, config.default_consolidated_excel)
    config.processing_details.append(f"Excel file written to {config.default_consolidated_excel}")
    config.processing_details.append("Consolidation phase complete.")

def tk_ui_main():
    # Create the main Tkinter window.
    root = tk.Tk()
    root.title("AIFuse - Processing & Consolidation Progress")
    root.geometry("600x400")

    # Create UI elements.
    progress_label = tk.Label(root, text="Processing Progress:")
    progress_label.pack(pady=5)

    progress_var = tk.DoubleVar()
    progress_bar = ttk.Progressbar(root, variable=progress_var, maximum=1, mode='determinate')
    progress_bar.pack(fill=tk.X, padx=10, pady=10)

    log_text = scrolledtext.ScrolledText(root, wrap=tk.WORD, height=10)
    log_text.pack(fill=tk.BOTH, padx=10, pady=10, expand=True)

    # Check for resume option using the shared function.
    tk_check_resume_option(root)

    processing_done = threading.Event()

    def update_ui():
        total = config.total_cases if config.total_cases else 1
        progress_bar.config(maximum=total)
        progress_var.set(config.cases_processed)
        log_text.delete(1.0, tk.END)
        with config.details_lock:
            for msg in config.processing_details:
                log_text.insert(tk.END, msg + "\n")
        root.after(500, update_ui)

    update_ui()

    def run_processing():
        processing.processing_main()
        processing_done.set()

    processing_thread = threading.Thread(target=run_processing)
    processing_thread.start()

    def check_and_run_consolidation():
        if processing_done.is_set():
            config.processing_details.append("Processing phase complete. Starting consolidation...")
            consolidation_thread = threading.Thread(target=run_consolidation_phase)
            consolidation_thread.start()
            consolidation_thread.join()  # Wait for consolidation to finish.
            def show_complete_popup():
                messagebox.showinfo("Complete", "All phases complete. Click OK to close the window.", parent=root)
                root.destroy()
            root.after(0, show_complete_popup)
        else:
            root.after(1000, check_and_run_consolidation)

    check_and_run_consolidation()

    def on_closing():
        if processing_thread.is_alive():
            messagebox.showinfo("Please wait", "Processing is still running. Please wait for it to finish.", parent=root)
        else:
            root.destroy()

    root.protocol("WM_DELETE_WINDOW", on_closing)
    root.mainloop()

if __name__ == "__main__":
    tk_ui_main()
