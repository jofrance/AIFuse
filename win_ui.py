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

# Global dictionary to manage jobs: job_id -> Job object
jobs_dict = {}

# Global UI components
job_list_tree = None
notebook = None
chat_window = None  # For chat window tracking

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
    stop_button = ttk.Button(tab, text="Stop Job",
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
    config_file = "config.ini"
    cp = configparser.ConfigParser()
    cp.optionxform = str  # Preserve key case
    cp.read(config_file)

    # Create the configuration editor window.
    config_win = tk.Toplevel(root)
    config_win.title("Configuration Editor")
    config_win.geometry("600x400")

    # Create a Notebook to hold one tab per section.
    nb = ttk.Notebook(config_win)
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
                add_win = tk.Toplevel(config_win)
                add_win.title("Add New Experiment")
                add_win.geometry("300x150")
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
                    friendly_name = name_entry.get().strip()
                    exp_id = id_entry.get().strip()
                    if friendly_name and exp_id:
                        # Insert the new experiment above the add button frame.
                        # Get current row of the add button frame.
                        current_rows = btn_frame.grid_info().get("row", row)
                        # Insert new widgets at that row.
                        new_label = tk.Label(frame, text=friendly_name)
                        new_label.grid(row=current_rows, column=0, padx=5, pady=5, sticky="w")
                        new_entry = tk.Entry(frame, width=50)
                        new_entry.insert(0, exp_id)
                        new_entry.grid(row=current_rows, column=1, padx=5, pady=5, sticky="w")
                        new_remove = ttk.Button(frame, text="Remove", width=10)
                        new_remove.config(command=lambda s=sec, k=friendly_name, lbl=new_label, ent=new_entry, rb=new_remove: remove_experiment_item(s, k, lbl, ent, rb))
                        new_remove.grid(row=current_rows, column=2, padx=5, pady=5)
                        entries[(sec, friendly_name)] = (new_label, new_entry, new_remove)
                        # Move the add button frame one row down.
                        btn_frame.grid_configure(row=current_rows+1)
                    add_win.destroy()
                add_btn = ttk.Button(dialog_btn_frame, text="Add", command=add_and_close, width=10)
                add_btn.pack(side=tk.LEFT, padx=10)
                cancel_btn = ttk.Button(dialog_btn_frame, text="Cancel", command=add_win.destroy, width=10)
                cancel_btn.pack(side=tk.LEFT, padx=10)
                add_win.transient(config_win)
                add_win.grab_set()
            add_exp_button = ttk.Button(add_button_frame, text="Add Experiment", command=add_experiment, width=1 )
            add_exp_button.pack(fill=tk.X)
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
    bottom_frame = tk.Frame(config_win)
    bottom_frame.pack(side=tk.BOTTOM, pady=10)

    def save_config():
        for (section, key), widget in entries.items():
            # For experiments section, widget is a tuple (label, entry, remove_button)
            if isinstance(widget, tuple):
                cp.set(section, key, widget[1].get())
            else:
                cp.set(section, key, widget.get())
        with open(config_file, "w", encoding="utf-8") as f:
            cp.write(f)
        messagebox.showinfo("Configuration", "Configuration saved successfully.")
        config_win.destroy()

    save_button = ttk.Button(bottom_frame, text="Save", command=save_config, width=10)
    save_button.pack(side=tk.LEFT, padx=10)
    cancel_button = ttk.Button(bottom_frame, text="Cancel", command=config_win.destroy, width=10)
    cancel_button.pack(side=tk.LEFT, padx=10)

    config_win.transient(root)
    config_win.grab_set()

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
    job = Job(file_selected, experiment_id)
    job.processed_tracking_file = unique_job_filename(job.input_file, job.experiment_id, "processed", "txt", job.job_id)
    job.api_401_tracking_file = unique_job_filename(job.input_file, job.experiment_id, "401", "txt", job.job_id)
    job.raw_output_file = unique_job_filename(job.input_file, job.experiment_id, "APIResponseRaw", "csv", job.job_id)
    job.api_response_file = unique_job_filename(job.input_file, job.experiment_id, "APIResponse", "csv", job.job_id)
    job.api_error_log_file = unique_job_filename(job.input_file, job.experiment_id, "APIError", "log", job.job_id)
    job.script_error_log_file = unique_job_filename(job.input_file, job.experiment_id, "ScriptError", "log", job.job_id)
    job.parsing_method = selected_parsing
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




def tk_ui_main():
    global job_list_tree, notebook, chat_window
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
    control_frame = tk.Frame(top_frame)
    control_frame.grid(row=0, column=1, sticky="ns", padx=5)
    new_job_button = ttk.Button(control_frame, text="New Job", command=lambda: start_new_job(root))
    new_job_button.pack(pady=2, fill=tk.X)
    stop_all_button = ttk.Button(control_frame, text="Stop All Jobs", command=stop_all_jobs)
    stop_all_button.pack(pady=2, fill=tk.X)
    clear_all_button = ttk.Button(control_frame, text="Clear All Jobs", command=clear_all_jobs)
    clear_all_button.pack(pady=2, fill=tk.X)
    chat_button = ttk.Button(control_frame, text="Chat", command=lambda: open_chat_from_button(root, chat_button))
    chat_button.pack(pady=2, fill=tk.X)
    # New Configuration button
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
            if job.status != "running":
                ui["cancel_button"].config(state=tk.DISABLED)
                ui["resume_button"].config(state=tk.NORMAL)
            else:
                ui["cancel_button"].config(state=tk.NORMAL)
                ui["resume_button"].config(state=tk.DISABLED)
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
