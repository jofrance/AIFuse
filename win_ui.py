import os
import sys
import threading
import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox, filedialog
import shutil
import config
import processing
import consolidation
import utils  # This module now contains the check_resume_status() function

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
        root.destroy()
        sys.exit(0)

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

# Define run_consolidation_phase before using it.
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

#############################
# New: Prompt user to save Excel file to another location.
#############################
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
    # After handling saving (or if not saving), close the application.
    root.destroy()
    sys.exit(0)

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
            root.destroy()
            sys.exit(0)
        else:
            msg = (f"Previous run detected.\nProcessed cases: {processed_count}\n"
                   f"Total input cases: {total_input}\n\n"
                   "Do you want to resume processing (Yes) or start fresh (No)?")
            result = messagebox.askyesno("Resume or Start Fresh", msg, parent=root)
            config.resume_mode = True if result else False

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
        config.resume_mode = False

def tk_ui_main():
    if config.ARGS is None:
        import argparse
        config.ARGS = argparse.Namespace(file="", threads=0, batch=0,
                                         consolidated_csv=config.default_consolidated_csv,
                                         consolidated_excel=config.default_consolidated_excel,
                                         no_ui=False, with_curses=False)

    root = tk.Tk()
    root.title("AIFuse - Processing & Consolidation Progress")
    root.geometry("600x400")
    root.eval('tk::PlaceWindow . center')

    # Check if a previous execution was completed.
    status = utils.check_resume_status()
    total_input = status["total_input"]
    processed_count = status["processed_count"]
    if os.path.exists(config.PROCESSED_TRACKING_FILE) and processed_count >= total_input and total_input > 0:
        answer = messagebox.askyesno("New Analysis?", 
            f"Previous execution completed for {total_input} cases.\nDo you want to analyze another file?",
            parent=root)
        if answer:
            if os.path.exists(config.PROCESSED_TRACKING_FILE):
                os.remove(config.PROCESSED_TRACKING_FILE)
            if os.path.exists(config.API_401_ERROR_TRACKING_FILE):
                os.remove(config.API_401_ERROR_TRACKING_FILE)
            config.ARGS.file = ""
        else:
            root.destroy()
            sys.exit(0)

    if not config.ARGS.file.strip():
        selected_file = prompt_for_input_file(root)
        if selected_file:
            config.ARGS.file = selected_file
        else:
            messagebox.showerror("Error", "No input file selected. Exiting.", parent=root)
            sys.exit(1)

    progress_label = tk.Label(root, text="Processing Progress:")
    progress_label.pack(pady=5)

    progress_var = tk.DoubleVar()
    progress_bar = ttk.Progressbar(root, variable=progress_var, maximum=1, mode='determinate')
    progress_bar.pack(fill=tk.X, padx=10, pady=10)

    log_text = scrolledtext.ScrolledText(root, wrap=tk.WORD, height=10)
    log_text.pack(fill=tk.BOTH, padx=10, pady=10, expand=True)

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

            def poll_consolidation():
                if consolidation_thread.is_alive():
                    root.after(1000, poll_consolidation)
                else:
                    # Once consolidation is done, prompt for saving the Excel file.
                    show_save_copy_prompt(root)
            poll_consolidation()
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
