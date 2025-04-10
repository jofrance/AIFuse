import os
import sys
import threading
import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox, filedialog
import shutil
import config
import processing
import consolidation
import utils
from config import generate_filename
from job_manager import Job, get_input_file_md5, save_job_state, load_all_jobs, clear_job_state
from log_config import logger
import itertools
import time
import configparser  # For configuration editing
import uuid  # For generating unique job IDs

# Global dictionary to manage jobs: job_id -> Job object
jobs_dict = {}

# Global UI components
job_list_tree = None
notebook = None
chat_window = None  # For chat window tracking
config_window = None
config_button = None  # Add this line to declare config_button globally

# Helper: Append part of the job_id to a generated filename to ensure uniqueness
def unique_job_filename(input_file, experiment_id, basename, extension, job_id):
    base = generate_filename(input_file, experiment_id, basename, extension)
    root_part, ext_part = os.path.splitext(base)
    return f"{root_part}_{job_id[:8]}{ext_part}"

# Ensure experiments keep their original casing
if hasattr(config, "CONFIG"):
    config.CONFIG.optionxform = str

def update_jobs_list():
    global job_list_tree
    for row in job_list_tree.get_children():
        job_list_tree.delete(row)
    experiments = {}
    if hasattr(config, "CONFIG") and config.CONFIG.has_section("Experiments"):
        for key, value in config.CONFIG.items("Experiments"):
            experiments[key] = value
    exp_name_map = {v: k for k, v in experiments.items()}
    for job in jobs_dict.values():
        exp_name = exp_name_map.get(job.experiment_id, job.experiment_id)
        job_list_tree.insert("", "end", iid=job.job_id,
                             values=(job.job_id, os.path.basename(job.input_file), exp_name, job.status))

def create_job_tab(job):
    global notebook
    tab = ttk.Frame(notebook)
    notebook.add(tab, text=f"Job {job.job_id[:8]}")
    
    # Progress bar
    progress_var = tk.DoubleVar(value=job.progress_done)
    progress_bar = ttk.Progressbar(tab, variable=progress_var, maximum=job.progress_total or 1)
    progress_bar.pack(fill=tk.X, padx=5, pady=5)
    
    # Frame for progress label and spinner
    progress_frame = tk.Frame(tab)
    progress_frame.pack(fill=tk.X, padx=5, pady=5)
    
    progress_label = ttk.Label(progress_frame, text=f"{job.progress_done} of {job.progress_total} cases processed")
    progress_label.pack(side=tk.LEFT)
    
    spinner_label = tk.Label(progress_frame, font=("Helvetica", 12))
    spinner_label.pack(side=tk.LEFT, padx=(5, 0))
    
    def start_spinner(label, job):
        spinner_cycle = itertools.cycle(["|", "/", "-", "\\"])
        def update_spinner():
            if job.status == "running":
                label.config(text=next(spinner_cycle))
            label.after(100, update_spinner)
        update_spinner()
    start_spinner(spinner_label, job)
    
    # Elapsed time label
    elapsed_time_label = ttk.Label(tab, text="Elapsed time: 00:00:00")
    elapsed_time_label.pack(fill=tk.X, padx=5, pady=5)
    if not hasattr(job, "start_time"):
        job.start_time = time.time()
    
    # Log text area
    log_text = scrolledtext.ScrolledText(tab, wrap=tk.WORD, height=10)
    log_text.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
    
    # Stop Job button
    stop_button = ttk.Button(tab, text="Pause Job",
                             command=lambda job_id=job.job_id: cancel_job(job_id))
    stop_button.pack(side=tk.LEFT, padx=5, pady=5)
    
    # Resume Job button (initially disabled)
    resume_button = ttk.Button(tab, text="Resume Job",
                               command=lambda job_id=job.job_id: resume_job(job_id),
                               state=tk.DISABLED)
    resume_button.pack(side=tk.LEFT, padx=5, pady=5)
    
    # Save Results button (disabled initially)
    save_button = ttk.Button(tab, text="Save Results",
                             command=lambda job=job: save_job_results(job), state=tk.DISABLED)
    save_button.pack(side=tk.RIGHT, padx=5, pady=5)
    
    job.ui = {
        "progress_var": progress_var,
        "progress_bar": progress_bar,
        "progress_label": progress_label,
        "spinner_label": spinner_label,
        "elapsed_time_label": elapsed_time_label,
        "log_text": log_text,
        "cancel_button": stop_button,
        "resume_button": resume_button,
        "save_button": save_button,
        "tab": tab,
        "last_log_index": 0
    }
    return tab

def cancel_job(job_id):
    if job_id in jobs_dict:
        job = jobs_dict[job_id]
        job.cancel_event.set()
        job.status = "stopped"
        job.log("Processing stopped.")
        update_jobs_list()
        job.ui["cancel_button"].config(state=tk.DISABLED)
        job.ui["resume_button"].config(state=tk.NORMAL)
        save_job_state(job)

def resume_job(job_id):
    job = jobs_dict.get(job_id)
    if not job:
        return
    job.resume_mode = True
    job.cancel_event.clear()
    job.status = "running"
    job.log("Job resumed by user.")
    job.ui["cancel_button"].config(state=tk.NORMAL)
    job.ui["resume_button"].config(state=tk.DISABLED)
    update_jobs_list()
    
    def run_resumed_job():
        processing.processing_main_job(job)
        if not job.cancel_event.is_set():
            job.status = "finished"
            job.log("Job finished processing.")
            original_cases = consolidation.load_original_cases(job.input_file)
            job.log(f"Loaded {len(original_cases)} original cases.")
            error_log = consolidation.load_error_log(job.api_error_log_file)
            job.log(f"Loaded {len(error_log)} error entries.")
        
            if job.parsing_method.upper() == "CSV":
                job.log("CSV consolidation Selected.")
                api_hdr, api_dict = consolidation.load_api_responses(job.api_response_file)
                if api_hdr:
                    job.log(f"API header found: {api_hdr}")
                else:
                    job.log("No API header found; using default placeholder.")
                total_api_rows = sum(len(v) for v in api_dict.values())
                job.log(f"Loaded {total_api_rows} API response entries.")
                consolidation.consolidate_data(job.input_file, original_cases, error_log,
                                               api_hdr, api_dict, job.consolidated_csv)
                utils.write_csv_to_excel(job.consolidated_csv, job.consolidated_excel)
                job.log("CSV consolidation complete.")
            elif job.parsing_method.upper() == "TXT":
                job.log("Plain Text consolidation complete.")
            elif job.parsing_method.upper() == "JSON":
                job.log("JSON consolidation complete.")
            else:
                job.log("Unknown parsing method. Defaulting to CSV consolidation.")
                api_hdr, api_dict = consolidation.load_api_responses(job.api_response_file)
                if api_hdr:
                    job.log(f"API header found: {api_hdr}")
                else:
                    job.log("No API header found; using default placeholder.")
                total_api_rows = sum(len(v) for v in api_dict.values())
                job.log(f"Loaded {total_api_rows} API response entries.")
                consolidation.consolidate_data(job.input_file, original_cases, error_log,
                                               api_hdr, api_dict, job.consolidated_csv)
                utils.write_csv_to_excel(job.consolidated_csv, job.consolidated_excel)
                job.log("CSV consolidation complete.")
        
            job.ui["save_button"].config(state=tk.NORMAL)
        save_job_state(job)
        update_jobs_list()
    threading.Thread(target=run_resumed_job, daemon=True).start()

def save_job_results(job):
    if job.parsing_method.upper() in ("TXT", "JSON"):
        default_file = job.consolidated_txt
        title = "Save Consolidated Text File As" if job.parsing_method.upper() == "TXT" else "Save Consolidated JSON File As"
        file_types = [("Text Files", "*.txt")]
        extension = ".txt"
    else:
        default_file = job.consolidated_excel
        title = "Save Consolidated Excel File As"
        file_types = [("Excel Files", "*.xlsx")]
        extension = ".xlsx"
    dest_file = filedialog.asksaveasfilename(
        title=title,
        defaultextension=extension,
        filetypes=file_types,
        initialfile=os.path.basename(default_file)
    )
    if dest_file:
        try:
            shutil.copy(default_file, dest_file)
            messagebox.showinfo("Success", f"File saved successfully for Job {job.job_id[:8]}.")
            job.status = "finished"
            job.log("Job output saved. Clearing job from UI.")
            update_jobs_list()
            notebook.forget(job.ui["tab"])
            clear_job_state(job.job_id)
            del jobs_dict[job.job_id]
            update_jobs_list()
        except Exception as e:
            messagebox.showerror("Error", f"Failed to save file for Job {job.job_id[:8]}: {e}")

def open_configuration_window(root):
    import configparser
    global config_window, config_button  # Add global declarations
    
    # Check if window is already open
    if config_window is not None and tk.Toplevel.winfo_exists(config_window):
        config_window.lift()  # Bring to front if already open
        return

    fixed_width = 600
    fixed_height = 400
    config_file = "config.ini"
    cp = configparser.ConfigParser()
    cp.optionxform = str  # Preserve key case
    cp.read(config_file)

    # Create the configuration editor window - FIX THIS LINE
    config_window = tk.Toplevel(root)  # Use the global variable directly
    config_window.title("Configuration Editor")
    # REMOVE THIS LINE: config_win = config_window  # This was overwriting the window with None
    
    config_button.config(state=tk.DISABLED)  # Disable the button while the window is open
    
    # Create a Notebook to hold one tab per section.
    nb = ttk.Notebook(config_window)  # Use config_window consistently
    nb.pack(fill=tk.BOTH, expand=True)
    
    # Dictionary to store widgets for each (section, key)
    # For experiments, we'll store a tuple: (label, entry, remove_button)
    entries = {}

    # Helper function to remove an experiment row.
    def remove_experiment_item(section, key, lbl, ent, rb):
        lbl.destroy()
        ent.destroy()
        rb.destroy()
        if (section, key) in entries:
            del entries[(section, key)]

    # Loop through each section in the config file.
    for section in cp.sections():
        if section.lower() in ["parsing", "parsingexplanations"]:
            continue  # Skip these sections
        # Create a frame for each section.
        frame = tk.Frame(nb)
        nb.add(frame, text=section)
        row = 0
        # For the Experiments section, create rows with label, entry, and remove button.
        if section.lower() == "experiments":
            for key, value in cp.items(section):
                name_label = tk.Label(frame, text=key)
                name_label.grid(row=row, column=0, padx=5, pady=5, sticky="w")
                entry = tk.Entry(frame, width=50)
                entry.insert(0, value)
                entry.grid(row=row, column=1, padx=5, pady=5, sticky="w")
                remove_btn = ttk.Button(frame, text="Remove", width=10)
                # Use default argument in lambda to capture current widgets.
                remove_btn.config(command=lambda s=section, k=key, lbl=name_label, ent=entry, rb=remove_btn: remove_experiment_item(s, k, lbl, ent, rb))
                remove_btn.grid(row=row, column=2, padx=5, pady=5)
                entries[(section, key)] = (name_label, entry, remove_btn)
                row += 1
            # Create a frame for the Add Experiment button; always fixed at the bottom.
            add_button_frame = tk.Frame(frame)
            add_button_frame.grid(row=row, column=0, columnspan=3, pady=10, sticky="ew")
            def add_experiment(sec=section, frame=frame, btn_frame=add_button_frame):
                fixed_width = 420
                fixed_height = 150
                
                add_win = tk.Toplevel(config_window)
                add_win.title("Add New Experiment")
                add_win.geometry(f"{fixed_width}x{fixed_height}")
                add_win.resizable(False, False)
                
                tk.Label(add_win, text="Experiment Friendly Name:").grid(row=0, column=0, padx=5, pady=5, sticky="w")
                name_entry = tk.Entry(add_win, width=30)
                name_entry.grid(row=0, column=1, padx=5, pady=5)
                tk.Label(add_win, text="Experiment ID:").grid(row=1, column=0, padx=5, pady=5, sticky="w")
                id_entry = tk.Entry(add_win, width=30)
                id_entry.grid(row=1, column=1, padx=5, pady=5)
                
                # Button frame for Add/Cancel in dialog
                dialog_btn_frame = tk.Frame(add_win)
                dialog_btn_frame.grid(row=2, column=0, columnspan=2, pady=10)
                
                def add_and_close():
                    # Get values from entries
                    name = name_entry.get().strip()
                    exp_id = id_entry.get().strip()
                    
                    # Validate both fields are filled
                    if not name or not exp_id:
                        messagebox.showerror("Error", "Both name and ID must be provided.", parent=add_win)
                        return
                    
                    # Add to config parser
                    cp.set(sec, name, exp_id)
                    
                    # Add to UI
                    row_count = len([k for s, k in entries.keys() if s == sec])
                    
                    # Create widgets for the new row
                    name_label = tk.Label(frame, text=name)
                    name_label.grid(row=row_count, column=0, padx=5, pady=5, sticky="w")
                    
                    entry = tk.Entry(frame, width=50)
                    entry.insert(0, exp_id)
                    entry.grid(row=row_count, column=1, padx=5, pady=5, sticky="w")
                    
                    remove_btn = ttk.Button(frame, text="Remove", width=10)
                    remove_btn.grid(row=row_count, column=2, padx=5, pady=5)
                    
                    # Configure remove button
                    remove_btn.config(command=lambda s=sec, k=name, lbl=name_label, 
                                       ent=entry, rb=remove_btn: 
                                       remove_experiment_item(s, k, lbl, ent, rb))
                    
                    # Add to entries dictionary
                    entries[(sec, name)] = (name_label, entry, remove_btn)
                    
                    # Move the Add Experiment button frame down to the row after the new experiment
                    btn_frame.grid_forget()
                    btn_frame.grid(row=row_count + 1, column=0, columnspan=3, pady=10, sticky="ew")
                    
                    # Close dialog
                    add_win.destroy()
                
                add_btn = ttk.Button(dialog_btn_frame, text="Add", command=add_and_close, width=10)
                add_btn.pack(side=tk.LEFT, padx=10)
                cancel_btn = ttk.Button(dialog_btn_frame, text="Cancel", command=add_win.destroy, width=10)
                cancel_btn.pack(side=tk.LEFT, padx=10)
                
                # Center the dialog on screen
                add_win.update_idletasks()
                screen_width = add_win.winfo_screenwidth()
                screen_height = add_win.winfo_screenheight()
                x = (screen_width // 2) - (fixed_width // 2)
                y = (screen_height // 2) - (fixed_height // 2)
                add_win.geometry(f"{fixed_width}x{fixed_height}+{x}+{y}")
                
                # Make it a modal dialog
                add_win.transient(config_window)
                add_win.grab_set()
            add_exp_button = ttk.Button(add_button_frame, text="Add Experiment", command=add_experiment, width=15)
            add_exp_button.pack(padx=5, pady=5)  # Remove fill=tk.X to avoid stretching
        else:
            # For non-Experiments sections, simply create Label and Entry.
            for key, value in cp.items(section):
                tk.Label(frame, text=key).grid(row=row, column=0, padx=5, pady=5, sticky="w")
                entry = tk.Entry(frame, width=50)
                entry.insert(0, value)
                entry.grid(row=row, column=1, padx=5, pady=5, sticky="w")
                entries[(section, key)] = entry
                row += 1

    # Bottom frame for Save and Cancel buttons.
    bottom_frame = tk.Frame(config_window)  # Use config_window consistently
    bottom_frame.pack(side=tk.BOTTOM, pady=10)

    def save_config():
        # First, clear experiment entries from CP so removed ones don't persist
        if cp.has_section("Experiments"):
            # Get all keys in the Experiments section
            experiment_keys = [key for key in cp.options("Experiments")]
            # Remove all experiment keys from the ConfigParser
            for key in experiment_keys:
                cp.remove_option("Experiments", key)
                
        # Now update with current entries from the UI
        for (section, key), widget in entries.items():
            # Make sure the section exists
            if not cp.has_section(section):
                cp.add_section(section)
                
            # For experiments section, widget is a tuple (label, entry, remove_button)
            if isinstance(widget, tuple):
                cp.set(section, key, widget[1].get())
            else:
                cp.set(section, key, widget.get())
                    
        # Create a merged config before writing
        merged_config = configparser.ConfigParser()
        merged_config.optionxform = str  # Preserve case sensitivity
        
        # First read existing config file (if any)
        merged_config.read(config_file)
        
        # IMPORTANT: Remove the Experiments section entirely from merged_config
        # to ensure deleted experiments don't come back
        if merged_config.has_section("Experiments"):
            merged_config.remove_section("Experiments")
        if cp.has_section("Experiments"):
            merged_config.add_section("Experiments")
        
        # Now update with all sections from cp
        for section in cp.sections():
            if not merged_config.has_section(section):
                merged_config.add_section(section)
            for key, value in cp.items(section):
                merged_config.set(section, key, value)
                
        # IMPORTANT: Preserve the original Parsing section instead of using hardcoded values
        # Only create default values if it doesn't exist in either place
        if not merged_config.has_section('Parsing') and not config.PARSING_CONFIG.has_section('Parsing'):
            merged_config.add_section('Parsing')
            # Use the values that match the original at app startup
            merged_config.set('Parsing', 'Comma Separated', 'CSV')
            merged_config.set('Parsing', 'Plain Text', 'TXT')
            merged_config.set('Parsing', 'API Full JSON', 'JSON')
        elif config.PARSING_CONFIG.has_section('Parsing'):
            # Copy from the original PARSING_CONFIG if it exists
            if not merged_config.has_section('Parsing'):
                merged_config.add_section('Parsing')
            for key, value in config.PARSING_CONFIG.items('Parsing'):
                merged_config.set('Parsing', key, value)
                
        # Do the same for ParsingExplanations
        if not merged_config.has_section('ParsingExplanations') and not config.PARSING_CONFIG.has_section('ParsingExplanations'):
            merged_config.add_section('ParsingExplanations')
            merged_config.set('ParsingExplanations', 'Comma Separated', 'Process data in CSV format with Excel output')
            merged_config.set('ParsingExplanations', 'Plain Text', 'Process data in plain text format')
            merged_config.set('ParsingExplanations', 'API Full JSON', 'Process raw API JSON response')
        elif config.PARSING_CONFIG.has_section('ParsingExplanations'):
            if not merged_config.has_section('ParsingExplanations'):
                merged_config.add_section('ParsingExplanations')
            for key, value in config.PARSING_CONFIG.items('ParsingExplanations'):
                merged_config.set('ParsingExplanations', key, value)
                
        # Now write the merged config
        with open(config_file, "w", encoding="utf-8") as f:
            merged_config.write(f)
        
        # IMPORTANT: Create new ConfigParser objects and reload from the file
        # This ensures we get exactly what was saved, not hardcoded values
        
        if hasattr(config, "CONFIG"):
            # Create a fresh ConfigParser with the same settings
            new_config = configparser.ConfigParser()
            new_config.optionxform = str  # Preserve case sensitivity
            new_config.read(config_file)
            
            # Replace the entire CONFIG object
            config.CONFIG = new_config
        
        if hasattr(config, "PARSING_CONFIG"):
            # Create a fresh ConfigParser with the same settings
            new_parsing_config = configparser.ConfigParser()
            new_parsing_config.optionxform = str  # Preserve case sensitivity
            new_parsing_config.read(config_file)
            
            # Replace the entire PARSING_CONFIG object
            config.PARSING_CONFIG = new_parsing_config
            
            # Debug output to verify correct sections were loaded
            print(f"Parsing sections after reload: {new_parsing_config.sections()}")
            if new_parsing_config.has_section('Parsing'):
                print(f"Loaded parsing methods: {dict(new_parsing_config.items('Parsing'))}")
        
        # Reload any specific config values that are stored as module-level variables
        if hasattr(config, "experimentId") and config.CONFIG.has_option("API", "experimentId"):
            config.experimentId = config.CONFIG.get("API", "experimentId")
        
        messagebox.showinfo("Configuration", "Configuration saved successfully.")
        config_window.destroy()
    
    # Create and add the Save and Cancel buttons to the bottom_frame
    save_button = ttk.Button(bottom_frame, text="Save", command=save_config, width=10)
    save_button.pack(side=tk.LEFT, padx=10)
    
    cancel_button = ttk.Button(bottom_frame, text="Cancel", command=config_window.destroy, width=10)
    cancel_button.pack(side=tk.LEFT, padx=10)
    
    def on_config_window_close():
        global config_window  # Move to beginning of function
        config_button.config(state=tk.NORMAL)
        config_window = None
    
    config_window.protocol("WM_DELETE_WINDOW", on_config_window_close)
    
    # Update save and cancel button functions to re-enable the config button
    def save_config_wrapped():
        global config_window  # Move to beginning of function
        save_config()
        config_button.config(state=tk.NORMAL)
        config_window = None
    
    def cancel_wrapped():
        global config_window  # Move to beginning of function
        config_window.destroy()
        config_button.config(state=tk.NORMAL)
        config_window = None
    
    # Replace the original button commands
    save_button.config(command=save_config_wrapped)
    cancel_button.config(command=cancel_wrapped)
    
    # Center the configuration window on screen
    config_window.update_idletasks()
    screen_width = config_window.winfo_screenwidth()
    screen_height = config_window.winfo_screenheight()
    x = (screen_width // 2) - (fixed_width // 2)
    y = (screen_height // 2) - (fixed_height // 2)
    config_window.geometry(f"{fixed_width}x{fixed_height}+{x}+{y}")

def start_new_job(main_window):
    print("JOBS_DICT KEYS:", list(jobs_dict.keys()))
    for job in jobs_dict.values():
        print(f"→ Job {job.job_id[:8]} | logs length={len(job.logs)} | progress={job.progress_done}/{job.progress_total}")
    file_selected = prompt_for_input_file(main_window)
    if not file_selected:
        messagebox.showerror("Error", "No input file selected. Job cancelled.", parent=main_window)
        return
    logger.info("File Selected:" + file_selected)
    selected_experiment = prompt_for_experiment_selection(main_window)
    if selected_experiment is None:
        messagebox.showinfo("Cancelled", "Experiment selection cancelled. Job not started.", parent=main_window)
        return
    logger.info("Experiment Selected:" + selected_experiment)
    config.experimentId = selected_experiment
    experiment_id = config.experimentId
    selected_parsing = prompt_for_parsing_method(main_window)
    if selected_parsing is None:
        messagebox.showinfo("Cancelled", "Parsing method selection cancelled. Job not started.", parent=main_window)
        return
    logger.info("Experiment Parsing:" + selected_parsing)
    
    # Add processing settings dialog
    processing_settings = show_processing_settings_dialog(main_window)
    if not processing_settings:
        return  # User canceled
    
    # Create job with processing settings
    job = Job(
        job_id=str(uuid.uuid4()),
        input_file=file_selected,
        experiment_id=experiment_id,
        experiment_name=selected_experiment,
        parsing_method=selected_parsing,
        threads=processing_settings["threads"],
        batch_size=processing_settings["batch_size"]
    )
    
    job.processed_tracking_file = unique_job_filename(job.input_file, job.experiment_id, "processed", "txt", job.job_id)
    job.api_401_tracking_file = unique_job_filename(job.input_file, job.experiment_id, "401", "txt", job.job_id)
    job.raw_output_file = unique_job_filename(job.input_file, job.experiment_id, "APIResponseRaw", "csv", job.job_id)
    job.api_response_file = unique_job_filename(job.input_file, job.experiment_id, "APIResponse", "csv", job.job_id)
    job.api_error_log_file = unique_job_filename(job.input_file, job.experiment_id, "APIError", "log", job.job_id)
    job.script_error_log_file = unique_job_filename(job.input_file, job.experiment_id, "ScriptError", "log", job.job_id)
    if job.parsing_method.upper() == "TXT":
        job.log("Plain Text consolidation Selected.")
        job.consolidated_txt = unique_job_filename(job.input_file, job.experiment_id, "Consolidated_Output", "txt", job.job_id)
        job.consolidation_lock = threading.Lock()
    elif job.parsing_method.upper() == "JSON":
        job.log("JSON consolidation Selected.")
        job.consolidated_txt = unique_job_filename(job.input_file, job.experiment_id, "Consolidated_Output", "txt", job.job_id)
        job.consolidation_lock = threading.Lock()
    else:
        job.consolidated_csv = unique_job_filename(job.input_file, job.experiment_id, "Consolidated_Output", "csv", job.job_id)
        job.consolidated_excel = unique_job_filename(job.input_file, job.experiment_id, "Consolidated_Output", "xlsx", job.job_id)
    jobs_dict[job.job_id] = job
    update_jobs_list()
    create_job_tab(job)
    print("🔸 After start_new_job(), jobs_dict keys:", list(jobs_dict.keys()))
    def run_job():
        processing.processing_main_job(job)
        if not job.cancel_event.is_set():
            job.status = "finished"
            job.log("Job finished processing.")
            original_cases = consolidation.load_original_cases(job.input_file)
            job.log(f"Loaded {len(original_cases)} original cases.")
            error_log = consolidation.load_error_log(job.api_error_log_file)
            job.log(f"Loaded {len(error_log)} error entries.")
            if job.parsing_method.upper() == "CSV":
                job.log("CSV consolidation Selected.")
                api_hdr, api_dict = consolidation.load_api_responses(job.api_response_file)
                if api_hdr:
                    job.log(f"API header found: {api_hdr}")
                else:
                    job.log("No API header found; using default placeholder.")
                total_api_rows = sum(len(v) for v in api_dict.values())
                job.log(f"Loaded {total_api_rows} API response entries.")
                consolidation.consolidate_data(job.input_file, original_cases, error_log,
                                               api_hdr, api_dict, job.consolidated_csv)
                utils.write_csv_to_excel(job.consolidated_csv, job.consolidated_excel)
                job.log("CSV consolidation complete.")
            elif job.parsing_method.upper() == "TXT":
                job.log("Plain Text consolidation complete.")
            elif job.parsing_method.upper() == "JSON":
                job.log("JSON consolidation complete.")
            else:
                job.log("Unknown parsing method. Defaulting to CSV consolidation.")
                api_hdr, api_dict = consolidation.load_api_responses(job.api_response_file)
                if api_hdr:
                    job.log(f"API header found: {api_hdr}")
                else:
                    job.log("No API header found; using default placeholder.")
                total_api_rows = sum(len(v) for v in api_dict.values())
                job.log(f"Loaded {total_api_rows} API response entries.")
                consolidation.consolidate_data(job.input_file, original_cases, error_log,
                                               api_hdr, api_dict, job.consolidated_csv)
                utils.write_csv_to_excel(job.consolidated_csv, job.consolidated_excel)
                job.log("CSV consolidation complete.")
            job.ui["save_button"].config(state=tk.NORMAL)
        else:
            job.log("Processing stopped.")
        save_job_state(job)
        update_jobs_list()
    threading.Thread(target=run_job, daemon=True).start()

def stop_all_jobs():
    for job in list(jobs_dict.values()):
        if job.status not in ["finished", "stopped"]:
            job.cancel_event.set()
            job.status = "stopped"
            job.log("Job stopped by Stop All.")
            job.ui["cancel_button"].config(state=tk.DISABLED)
            job.ui["resume_button"].config(state=tk.NORMAL)
            save_job_state(job)
    update_jobs_list()

def clear_all_jobs():
    stop_all_jobs()
    global jobs_dict
    jobs_dict.clear()
    jobs_state_dir = os.path.join(config.OUTPUT_DIR, "jobs_state")
    for filename in os.listdir(jobs_state_dir):
        if filename.endswith(".json"):
            os.remove(os.path.join(jobs_state_dir, filename))
    update_jobs_list()
    for tab in notebook.tabs():
        notebook.forget(tab)

def prompt_for_input_file(root):
    fixed_width = 300
    fixed_height = 150
    dialog = tk.Toplevel(root)
    dialog.title("Select Input File")
    dialog.geometry(f"{fixed_width}x{fixed_height}")
    dialog.transient(root)
    dialog.lift()
    dialog.focus_set()
    dialog.grab_set()
    content_frame = tk.Frame(dialog)
    content_frame.pack(expand=True, fill=tk.BOTH, padx=20, pady=20)
    label = tk.Label(content_frame, text="Please choose an input file (json or txt):")
    label.pack(pady=10)
    selected_file = {"file": ""}
    def browse():
        file_path = filedialog.askopenfilename(
            title="Select Input JSON File",
            filetypes=[("json Files", "*.json"), ("text Files", "*.txt"), ("All Files", "*.*")]
        )
        if file_path:
            selected_file["file"] = file_path
            dialog.destroy()
    def cancel():
        dialog.destroy()
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

def prompt_for_experiment_selection(root):
    fixed_width = 400
    fixed_height = 200
    dialog = tk.Toplevel(root)
    dialog.title("Select Experiment")
    dialog.geometry(f"{fixed_width}x{fixed_height}")
    dialog.transient(root)
    dialog.lift()
    dialog.focus_set()
    dialog.grab_set()
    content_frame = tk.Frame(dialog)
    content_frame.pack(expand=True, fill=tk.BOTH, padx=20, pady=20)
    label = tk.Label(content_frame, text="Please select an experiment:")
    label.pack(pady=10)
    experiments = {}
    if hasattr(config, "CONFIG") and config.CONFIG.has_section("Experiments"):
        for key, value in config.CONFIG.items("Experiments"):
            experiments[key] = value
    if not experiments:
        dialog.destroy()
        return None
    experiment_var = tk.StringVar()
    max_length = max(len(s) for s in experiments.keys())
    combobox = ttk.Combobox(content_frame, textvariable=experiment_var,
                              values=list(experiments.keys()), state="readonly",
                              width=max_length + 2)
    combobox.pack(pady=10)
    current_exp = None
    for name, exp_id in experiments.items():
        if exp_id == config.experimentId:
            current_exp = name
            break
    if current_exp:
        combobox.set(current_exp)
    else:
        combobox.current(0)
    result = {"experiment": None}
    def on_ok():
        selected = experiment_var.get()
        if selected in experiments:
            result["experiment"] = experiments[selected]
        dialog.destroy()
    def on_cancel():
        result["experiment"] = None
        dialog.destroy()
    button_frame = tk.Frame(content_frame)
    button_frame.pack(pady=10)
    ok_button = ttk.Button(button_frame, text="OK", command=on_ok)
    ok_button.pack(side=tk.LEFT, padx=10)
    cancel_button = ttk.Button(button_frame, text="Cancel", command=on_cancel)
    cancel_button.pack(side=tk.LEFT, padx=10)
    dialog.update_idletasks()
    screen_width = dialog.winfo_screenwidth()
    screen_height = dialog.winfo_screenheight()
    x = (screen_width // 2) - (fixed_width // 2)
    y = (screen_height // 2) - (fixed_height // 2)
    dialog.geometry(f"{fixed_width}x{fixed_height}+{x}+{y}")
    dialog.wait_window()
    return result["experiment"]

def prompt_for_parsing_method(root):
    fixed_width = 400
    fixed_height = 300
    dialog = tk.Toplevel(root)
    dialog.title("Select Parsing Method")
    dialog.geometry(f"{fixed_width}x{fixed_height}")
    dialog.transient(root)
    dialog.lift()
    dialog.focus_set()
    dialog.grab_set()
    content_frame = tk.Frame(dialog)
    content_frame.pack(expand=True, fill=tk.BOTH, padx=20, pady=20)
    label = tk.Label(content_frame, text="Please select a parsing method:")
    label.pack(pady=10)
    parsing_methods = {}
    if hasattr(config, "PARSING_CONFIG") and config.PARSING_CONFIG.has_section("Parsing"):
        for key, value in config.PARSING_CONFIG.items("Parsing"):
            parsing_methods[key] = value
    if not parsing_methods:
        dialog.destroy()
        return None
    parsing_var = tk.StringVar()
    max_length = max(len(s) for s in parsing_methods.keys())
    combobox = ttk.Combobox(content_frame, textvariable=parsing_var,
                              values=list(parsing_methods.keys()), state="readonly",
                              width=max_length + 2)
    combobox.pack(pady=10)
    combobox.current(0)
    explanation_label = tk.Label(content_frame, text="", wraplength=fixed_width-40, justify=tk.LEFT)
    explanation_label.pack(pady=10)
    def update_explanation(event=None):
        selection = parsing_var.get()
        explanation = config.PARSING_CONFIG.get("ParsingExplanations", selection,
                                                 fallback="No explanation available for this method.")
        explanation_label.config(text=explanation)
    combobox.bind("<<ComboboxSelected>>", update_explanation)
    update_explanation()
    result = {"parsing": None}
    def on_ok():
        selected = parsing_var.get()
        if selected in parsing_methods:
            result["parsing"] = parsing_methods[selected]
        dialog.destroy()
    def on_cancel():
        result["parsing"] = None
        dialog.destroy()
    button_frame = tk.Frame(content_frame)
    button_frame.pack(pady=10)
    ok_button = ttk.Button(button_frame, text="OK", command=on_ok)
    ok_button.pack(side=tk.LEFT, padx=10)
    cancel_button = ttk.Button(button_frame, text="Cancel", command=on_cancel)
    cancel_button.pack(side=tk.LEFT, padx=10)
    dialog.update_idletasks()
    screen_width = dialog.winfo_screenwidth()
    screen_height = dialog.winfo_screenheight()
    x = (screen_width // 2) - (fixed_width // 2)
    y = (screen_height // 2) - (fixed_height // 2)
    dialog.geometry(f"{fixed_width}x{fixed_height}+{x}+{y}")
    dialog.wait_window()
    return result["parsing"]

def show_processing_settings_dialog(parent):
    """Show dialog for configuring processing settings (threading/batching)"""
    fixed_width = 400
    fixed_height = 300
    
    dialog = tk.Toplevel(parent)
    dialog.title("Processing Settings")
    dialog.geometry(f"{fixed_width}x{fixed_height}")
    dialog.resizable(False, False)
    dialog.transient(parent)
    dialog.grab_set()

    # Container frame
    main_frame = ttk.Frame(dialog, padding="10")
    main_frame.pack(fill=tk.BOTH, expand=True)

    # Threading settings
    thread_frame = ttk.LabelFrame(main_frame, text="Threading Settings")
    thread_frame.pack(fill=tk.X, pady=(0, 10))

    thread_enabled = tk.BooleanVar(value=False)
    ttk.Checkbutton(thread_frame, text="Enable threading", variable=thread_enabled).pack(anchor=tk.W, padx=5, pady=5)

    thread_count_frame = ttk.Frame(thread_frame)
    thread_count_frame.pack(fill=tk.X, padx=5, pady=5)
    ttk.Label(thread_count_frame, text="Number of threads:").pack(side=tk.LEFT)
    
    thread_count = tk.IntVar(value=4)
    thread_spinner = ttk.Spinbox(thread_count_frame, from_=1, to=32, textvariable=thread_count, width=5, state="disabled")
    thread_spinner.pack(side=tk.LEFT, padx=5)

    # Enable/disable thread count spinner based on checkbox
    def toggle_thread_spinner(*args):
        thread_spinner.configure(state="normal" if thread_enabled.get() else "disabled")
    thread_enabled.trace_add("write", toggle_thread_spinner)

    # Batching settings
    batch_frame = ttk.LabelFrame(main_frame, text="Case Grouping Settings")
    batch_frame.pack(fill=tk.X, pady=(0, 10))

    batch_enabled = tk.BooleanVar(value=False)
    ttk.Checkbutton(batch_frame, text="Enable case grouping (for thread efficiency)", variable=batch_enabled).pack(anchor=tk.W, padx=5, pady=5)

    batch_size_frame = ttk.Frame(batch_frame)
    batch_size_frame.pack(fill=tk.X, padx=5, pady=5)
    ttk.Label(batch_size_frame, text="Group size:").pack(side=tk.LEFT)
    
    batch_size = tk.IntVar(value=10)
    batch_spinner = ttk.Spinbox(batch_size_frame, from_=2, to=100, textvariable=batch_size, width=5, state="disabled")
    batch_spinner.pack(side=tk.LEFT, padx=5)

    # Enable/disable batch size spinner based on checkbox
    def toggle_batch_spinner(*args):
        batch_spinner.configure(state="normal" if batch_enabled.get() else "disabled")
    batch_enabled.trace_add("write", toggle_batch_spinner)

    # Help text
    help_text = "Threading: Process multiple cases concurrently\nGrouping: Group cases into batches for processing on each thread" 
    ttk.Label(main_frame, text=help_text, foreground="gray").pack(anchor=tk.W, pady=5)

    # Buttons
    button_frame = ttk.Frame(main_frame)
    button_frame.pack(fill=tk.X, pady=10)

    result = {"confirmed": False, "threads": 0, "batch_size": 0}

    def on_confirm():
        result["confirmed"] = True
        result["threads"] = thread_count.get() if thread_enabled.get() else 0
        result["batch_size"] = batch_size.get() if batch_enabled.get() else 0
        dialog.destroy()

    ttk.Button(button_frame, text="Cancel", command=dialog.destroy).pack(side=tk.LEFT, padx=5)
    ttk.Button(button_frame, text="Confirm", command=on_confirm).pack(side=tk.RIGHT, padx=5)

    # Center the dialog on screen
    dialog.update_idletasks()
    screen_width = dialog.winfo_screenwidth()
    screen_height = dialog.winfo_screenheight()
    x = (screen_width // 2) - (fixed_width // 2)
    y = (screen_height // 2) - (fixed_height // 2)
    dialog.geometry(f"{fixed_width}x{fixed_height}+{x}+{y}")

    parent.wait_window(dialog)
    return result if result["confirmed"] else None

def show_job_details(job_id):
        
    # Add threading and batching info to details display
    job = jobs_dict.get(job_id)
    if job:
        threading_text = f"Threading: {'Enabled (' + str(job.threads) + ' threads)' if job.threads > 0 else 'Disabled'}"
        batching_text = f"Batching: {'Enabled (batch size: ' + str(job.batch_size) + ')' if job.batch_size > 0 else 'Disabled'}"
        details += f"\n{threading_text}\n{batching_text}"
    
    
def tk_ui_main():
    global job_list_tree, notebook, chat_window, config_button  # Include config_button here
    
    # Load unfinished jobs from file
    loaded_jobs = load_all_jobs()
    if loaded_jobs:
        for job in loaded_jobs.values():
            if job.status != "finished":
                jobs_dict[job.job_id] = job

    if config.ARGS is None:
        import argparse
        config.ARGS = argparse.Namespace(file="", threads=0, batch=0,
                                           consolidated_csv=config.default_consolidated_csv,
                                           consolidated_excel=config.default_consolidated_excel,
                                           no_ui=False, with_curses=False)
    root = tk.Tk()
    root.title("AIFuse - Multi-Job Processing & Consolidation")
    root.geometry("1050x600")
    main_frame = tk.Frame(root)
    main_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
    top_frame = tk.Frame(main_frame)
    top_frame.pack(fill=tk.X, padx=5, pady=5)
    top_frame.columnconfigure(0, weight=3)
    top_frame.columnconfigure(1, weight=1, minsize=200)
    job_list_tree = ttk.Treeview(top_frame, columns=("Job ID", "Input File", "Experiment", "Status"),
                                 show="headings", height=5)
    job_list_tree.heading("Job ID", text="Job ID")
    job_list_tree.heading("Input File", text="Input File")
    job_list_tree.heading("Experiment", text="Experiment")
    job_list_tree.heading("Status", text="Status")
    job_list_tree.grid(row=0, column=0, sticky="nsew")
    
    # Create the control frame
    control_frame = tk.Frame(top_frame)
    control_frame.grid(row=0, column=1, sticky="ns", padx=5)
    
    new_job_button = ttk.Button(control_frame, text="New Job", command=lambda: start_new_job(root))
    new_job_button.pack(pady=2, fill=tk.X)
    stop_all_button = ttk.Button(control_frame, text="Pause All Jobs", command=stop_all_jobs)
    stop_all_button.pack(pady=2, fill=tk.X)
    clear_all_button = ttk.Button(control_frame, text="Delete All Jobs", command=clear_all_jobs)
    clear_all_button.pack(pady=2, fill=tk.X)
    chat_button = ttk.Button(control_frame, text="Chat", command=lambda: open_chat_from_button(root, chat_button))
    chat_button.pack(pady=2, fill=tk.X)
    
    # KEEP ONLY THIS ONE Configuration button
    config_button = ttk.Button(control_frame, text="Configuration", command=lambda: open_configuration_window(root))
    config_button.pack(pady=2, fill=tk.X)
    
    quit_button = ttk.Button(control_frame, text="Quit", command=lambda: on_quit(root))
    quit_button.pack(pady=2, fill=tk.X)
    
    notebook_frame = tk.Frame(main_frame)
    notebook_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
    notebook = ttk.Notebook(notebook_frame)
    notebook.pack(fill=tk.BOTH, expand=True)
    
    for job in jobs_dict.values():
        create_job_tab(job)
    update_jobs_list()
    
    def update_ui():
        for job in jobs_dict.values():
            ui = job.ui
            ui["progress_var"].set(job.progress_done)
            ui["progress_bar"].config(maximum=job.progress_total or 1)
            ui["progress_label"].config(text=f"{job.progress_done} of {job.progress_total} cases processed")
            if hasattr(job, "start_time") and job.status == "running":
                elapsed = time.time() - job.start_time
                hours, rem = divmod(elapsed, 3600)
                minutes, seconds = divmod(rem, 60)
                elapsed_str = f"{int(hours):02}:{int(minutes):02}:{int(seconds):02}"
                ui["elapsed_time_label"].config(text=f"Elapsed time: {elapsed_str}")
            # Update button states based on job.status.
            if job.status == "running":
                ui["cancel_button"].config(state=tk.NORMAL)
                ui["resume_button"].config(state=tk.DISABLED)
            elif job.status == "finished":
                # If job is finished, disable both buttons
                ui["cancel_button"].config(state=tk.DISABLED)
                ui["resume_button"].config(state=tk.DISABLED)
            else:  # stopped, paused, etc.
                ui["cancel_button"].config(state=tk.DISABLED)
                ui["resume_button"].config(state=tk.NORMAL)
            if not ui.get("last_log_index"):
                ui["last_log_index"] = 0
            new_entries = job.logs[ui["last_log_index"]:]
            for entry in new_entries:
                ui["log_text"].insert(tk.END, entry+"\n")
            ui["last_log_index"] = len(job.logs)
        root.after(500, update_ui)
    update_ui()
    root.mainloop()

def on_quit(root):
    for job in jobs_dict.values():
        save_job_state(job)
    root.destroy()

def open_chat_from_button(root, chat_button):
    global chat_window
    if chat_window is None or not tk.Toplevel.winfo_exists(chat_window):
        import chat
        chat_window = chat.open_chat_window(root)
        chat_button.config(state=tk.DISABLED)
        chat_window.protocol("WM_DELETE_WINDOW", lambda: on_chat_close(chat_window, chat_button))

def on_chat_close(window, chat_button):
    global chat_window
    window.destroy()
    chat_button.config(state=tk.NORMAL)
    chat_window = None

if __name__ == "__main__":
    tk_ui_main()

