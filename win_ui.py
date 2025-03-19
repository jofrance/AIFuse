import os
import sys
import threading
import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox, filedialog
import shutil
import config
import processing
import consolidation
import utils  # Contains check_resume_status()

###########################################
# Configuration validation function.
###########################################
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
        messagebox.showerror("Configuration Error", "Missing configuration: " + ", ".join(missing))
        sys.exit(1)

###########################################
# Popup to prompt for the input file.
###########################################
def prompt_for_input_file(root):
    fixed_width = 300
    fixed_height = 150

    dialog = tk.Toplevel(root)
    dialog.title("Select Input File")
    dialog.geometry(f"{fixed_width}x{fixed_height}")
    dialog.transient(root)
    dialog.lift()
    dialog.focus_force()
    dialog.grab_set()

    content_frame = tk.Frame(dialog)
    content_frame.pack(expand=True, fill=tk.BOTH, padx=20, pady=20)

    label = tk.Label(content_frame, text="Please choose an input JSON file:")
    label.pack(pady=10)

    selected_file = {"file": ""}

    def browse():
        file_path = filedialog.askopenfilename(
            title="Select Input JSON File",
            filetypes=[("JSON Files", "*.json"), ("All Files", "*.*")]
        )
        if file_path:
            selected_file["file"] = file_path
            dialog.destroy()

    def cancel():
        dialog.destroy()
        # Instead of exiting, just return; caller will handle missing file.
    
    button_frame = tk.Frame(content_frame)
    button_frame.pack(pady=10)
    browse_button = ttk.Button(button_frame, text="Browse", command=browse)
    browse_button.pack(side=tk.LEFT, padx=10)
    cancel_button = ttk.Button(button_frame, text="Cancel", command=cancel)
    cancel_button.pack(side=tk.LEFT, padx=10)

    dialog.update_idletasks()
    screen_width = dialog.winfo_screenwidth()
    screen_height = dialog.winfo_screenheight()
    x = (screen_width // 2) - (fixed_width // 2)
    y = (screen_height // 2) - (fixed_height // 2)
    dialog.geometry(f"{fixed_width}x{fixed_height}+{x}+{y}")

    dialog.wait_window()
    return selected_file["file"]

###########################################
# Popup to prompt for experiment selection.
###########################################
def prompt_for_experiment_selection(root):
    fixed_width = 400
    fixed_height = 200

    dialog = tk.Toplevel(root)
    dialog.title("Select Experiment")
    dialog.geometry(f"{fixed_width}x{fixed_height}")
    dialog.transient(root)
    dialog.lift()
    dialog.focus_force()
    dialog.grab_set()

    content_frame = tk.Frame(dialog)
    content_frame.pack(expand=True, fill=tk.BOTH, padx=20, pady=20)

    label = tk.Label(content_frame, text="Please select an experiment:")
    label.pack(pady=10)

    if hasattr(config, "CONFIG") and config.CONFIG.has_section("Experiments"):
        experiments = dict(config.CONFIG.items("Experiments"))
    else:
        experiments = {}

    if not experiments:
        dialog.destroy()
        return

    experiment_var = tk.StringVar()
    combobox = ttk.Combobox(content_frame, textvariable=experiment_var,
                            values=list(experiments.keys()), state="readonly")
    combobox.pack(pady=10)

    default_name = None
    for name, exp_id in experiments.items():
        if exp_id == config.experimentId:
            default_name = name
            break
    if default_name:
        combobox.set(default_name)
    else:
        combobox.current(0)
        config.experimentId = experiments[combobox.get()]

    def on_ok():
        selected = experiment_var.get()
        if selected in experiments:
            config.experimentId = experiments[selected]
        dialog.destroy()

    ok_button = ttk.Button(content_frame, text="OK", command=on_ok)
    ok_button.pack(pady=10)

    dialog.update_idletasks()
    screen_width = dialog.winfo_screenwidth()
    screen_height = dialog.winfo_screenheight()
    x = (screen_width // 2) - (fixed_width // 2)
    y = (screen_height // 2) - (fixed_height // 2)
    dialog.geometry(f"{fixed_width}x{fixed_height}+{x}+{y}")

    dialog.wait_window()
    return

###########################################
# Popup to save the consolidated Excel file.
# After saving (or not), control returns to the main window.
###########################################
def show_save_copy_prompt(root):
    save_copy = messagebox.askyesno("Save Copy", 
        "All phases complete.\nWould you like to save a copy of the consolidated Excel output to another location?", 
        parent=root)
    if save_copy:
        dest_file = filedialog.asksaveasfilename(
            title="Save Consolidated Excel File As",
            defaultextension=".xlsx",
            filetypes=[("Excel Files", "*.xlsx")],
            initialfile=os.path.basename(config.default_consolidated_excel),
            parent=root
        )
        if dest_file:
            try:
                shutil.copy(config.default_consolidated_excel, dest_file)
                messagebox.showinfo("Success", "Excel file saved successfully.", parent=root)
            except Exception as e:
                messagebox.showerror("Error", f"Failed to save file: {e}", parent=root)
    # Do not close the application; simply return control.

###########################################
# Consolidation phase function.
###########################################
def run_consolidation_phase():
    config.processing_details.append("Starting consolidation phase...")
    original_file = config.ARGS.file
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

###########################################
# Option to check resume status (if needed).
###########################################
def tk_check_resume_option(root):
    status = utils.check_resume_status()
    total_input = status["total_input"]
    processed_count = status["processed_count"]

    if os.path.exists(config.PROCESSED_TRACKING_FILE):
        if processed_count == 0:
            config.resume_mode = False
            return
        if processed_count >= total_input:
            messagebox.showinfo("All Cases Processed",
                                f"All {total_input} cases are already processed. Nothing to resume.",
                                parent=root)
            return
        else:
            msg = (f"Previous run detected.\nProcessed cases: {processed_count}\n"
                   f"Total input cases: {total_input}\n\n"
                   "Do you want to resume processing (Yes) or start fresh (No)?")
            result = messagebox.askyesno("Resume or Start Fresh", msg, parent=root)
            config.resume_mode = True if result else False

            api401_file = os.path.abspath(config.API_401_ERROR_TRACKING_FILE)
            if config.resume_mode and os.path.exists(api401_file):
                with open(config.API_401_ERROR_TRACKING_FILE, 'r') as f:
                    retry_lines = [line.strip() for line in f if line.strip()]
                if retry_lines:
                    msg2 = (f"There are {len(retry_lines)} cases with persistent 401 errors.\n"
                            "Do you want to retry these errors (Yes) or skip them (No)?")
                    result2 = messagebox.askyesno("Retry 401 Errors", msg2, parent=root)
                    config.retry_401_flag = True if result2 else False
    else:
        config.resume_mode = False

###########################################
# Function to start a new job.
# Triggered when the "New Job" button is pressed.
###########################################
def start_new_job(root, progress_bar, progress_var, log_text, new_job_button):
    # Disable the New Job button during processing.
    new_job_button.config(state=tk.DISABLED)
    
    # Clear previous job details.
    config.processing_details.clear()
    config.cases_processed = 0
    config.total_cases = 0

    # Prompt for file selection.
    file_selected = prompt_for_input_file(root)
    if not file_selected:
        messagebox.showerror("Error", "No input file selected. Job cancelled.", parent=root)
        new_job_button.config(state=tk.NORMAL)
        return
    config.ARGS.file = file_selected

    # Prompt for experiment selection.
    prompt_for_experiment_selection(root)

    # Build per-run tracking and output filenames using the MD5 + experiment ID convention.
    from config import generate_filename
    config.PROCESSED_TRACKING_FILE = generate_filename(config.ARGS.file, config.experimentId, "processed", "txt")
    config.API_401_ERROR_TRACKING_FILE = generate_filename(config.ARGS.file, config.experimentId, "401", "txt")
    config.RAW_OUTPUT_FILE = generate_filename(config.ARGS.file, config.experimentId, "APIResponseRaw", "csv")
    config.API_RESPONSE_FILE = generate_filename(config.ARGS.file, config.experimentId, "APIResponse", "csv")
    config.API_ERROR_LOG_FILE = generate_filename(config.ARGS.file, config.experimentId, "APIError", "log")
    config.SCRIPT_ERROR_LOG_FILE = generate_filename(config.ARGS.file, config.experimentId, "ScriptError", "log")
    config.default_consolidated_csv = generate_filename(config.ARGS.file, config.experimentId, "Consolidated_Output", "csv")
    config.default_consolidated_excel = generate_filename(config.ARGS.file, config.experimentId, "Consolidated_Output", "xlsx")

    # Duplicate detection: check if any output/tracking files already exist.
    duplicate_files = []
    for file in [config.PROCESSED_TRACKING_FILE, config.API_401_ERROR_TRACKING_FILE,
                 config.RAW_OUTPUT_FILE, config.API_RESPONSE_FILE,
                 config.API_ERROR_LOG_FILE, config.SCRIPT_ERROR_LOG_FILE,
                 config.default_consolidated_csv, config.default_consolidated_excel]:
        if os.path.exists(file):
            duplicate_files.append(file)
    if duplicate_files:
        answer = messagebox.askyesno("Duplicate Execution Detected",
            "A result file already exists for this set of cases and experiment.\nDo you want to re-run and overwrite these files?",
            parent=root)
        if answer:
            for file in duplicate_files:
                try:
                    os.remove(file)
                except Exception as e:
                    messagebox.showerror("Error", f"Could not remove file {file}: {e}", parent=root)
        else:
            new_job_button.config(state=tk.NORMAL)
            return

    # For a new job, always start fresh.
    config.resume_mode = False
    if os.path.exists(config.PROCESSED_TRACKING_FILE):
        os.remove(config.PROCESSED_TRACKING_FILE)
    processing.clear_output_files()
    processing.clear_401_tracking_file()

    # Check resume option (if applicable).
    tk_check_resume_option(root)

    # Start processing in a separate thread.
    processing_done = threading.Event()
    def run_processing():
        processing.processing_main()
        processing_done.set()
    processing_thread = threading.Thread(target=run_processing)
    processing_thread.start()

    # Update UI periodically during processing.
    def update_ui():
        total = config.total_cases if config.total_cases else 1
        progress_bar.config(maximum=total)
        progress_var.set(config.cases_processed)
        log_text.delete(1.0, tk.END)
        with config.details_lock:
            for msg in config.processing_details:
                log_text.insert(tk.END, msg + "\n")
        if not processing_done.is_set():
            root.after(500, update_ui)
        else:
            # After processing, run consolidation.
            config.processing_details.append("Processing phase complete. Starting consolidation...")
            consolidation_thread = threading.Thread(target=run_consolidation_phase)
            consolidation_thread.start()
            consolidation_thread.join()
            # After consolidation, prompt for saving a copy.
            show_save_copy_prompt(root)
            # Re-enable the New Job button.
            new_job_button.config(state=tk.NORMAL)
    update_ui()

###########################################
# Main Windows UI Function.
# This creates the persistent main window with a "New Job" button.
###########################################
def tk_ui_main():
    # Validate configuration before starting.
    validate_config()
    
    if config.ARGS is None:
        import argparse
        config.ARGS = argparse.Namespace(file="", threads=0, batch=0,
                                           consolidated_csv=config.default_consolidated_csv,
                                           consolidated_excel=config.default_consolidated_excel,
                                           no_ui=False, with_curses=False)

    root = tk.Tk()
    root.title("AIFuse - Processing & Consolidation")
    root.geometry("600x400")
    root.eval('tk::PlaceWindow . center')

    # Main UI frame.
    main_frame = tk.Frame(root)
    main_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

    # "New Job" button.
    new_job_button = ttk.Button(main_frame, text="New Job",
                                command=lambda: start_new_job(root, progress_bar, progress_var, log_text, new_job_button))
    new_job_button.pack(pady=10)

    # Processing progress label and progress bar.
    progress_label = tk.Label(main_frame, text="Processing Progress:")
    progress_label.pack(pady=5)
    progress_var = tk.DoubleVar()
    progress_bar = ttk.Progressbar(main_frame, variable=progress_var, maximum=1, mode='determinate')
    progress_bar.pack(fill=tk.X, padx=10, pady=10)

    # Log text area.
    log_text = scrolledtext.ScrolledText(main_frame, wrap=tk.WORD, height=10)
    log_text.pack(fill=tk.BOTH, padx=10, pady=10, expand=True)

    root.mainloop()

if __name__ == "__main__":
    tk_ui_main()
