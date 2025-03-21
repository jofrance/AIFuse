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

# Global dictionary to manage jobs: job_id -> Job object
jobs_dict = {}

# Global UI components
job_list_tree = None
notebook = None

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
    # Clear the treeview
    for row in job_list_tree.get_children():
        job_list_tree.delete(row)
    # Retrieve experiments mapping from config preserving original casing
    experiments = {}
    if hasattr(config, "CONFIG") and config.CONFIG.has_section("Experiments"):
        #for key in config.CONFIG.options("Experiments"):
         #   experiments[key] = config.CONFIG.get("Experiments", key)
        for key, value in config.CONFIG.items("Experiments"):
            experiments[key] = value
    # Reverse mapping: experiment ID -> experiment friendly name
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
    # Log text area (manual scrolling)
    log_text = scrolledtext.ScrolledText(tab, wrap=tk.WORD, height=10)
    log_text.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
    # Stop Job button
    stop_button = ttk.Button(tab, text="Stop Job",
                             command=lambda job_id=job.job_id: cancel_job(job_id))
    stop_button.pack(side=tk.LEFT, padx=5, pady=5)
    # Resume Job button
    resume_button = ttk.Button(tab, text="Resume Job",
                               command=lambda job_id=job.job_id: resume_job(job_id))
    resume_button.pack(side=tk.LEFT, padx=5, pady=5)
    # Save Results button (disabled initially)
    save_button = ttk.Button(tab, text="Save Results",
                             command=lambda job=job: save_job_results(job), state=tk.DISABLED)
    save_button.pack(side=tk.RIGHT, padx=5, pady=5)
    
    # Store UI components in the job object for later updates
    job.ui = {
        "progress_var": progress_var,
        "progress_bar": progress_bar,
        "log_text": log_text,
        "cancel_button": stop_button,
        "resume_button": resume_button,
        "save_button": save_button,
        "tab": tab
    }
    # If job is running, disable resume button; otherwise enable it.
    if job.status == "running":
        resume_button.config(state=tk.DISABLED)
    else:
        resume_button.config(state=tk.NORMAL)

def cancel_job(job_id):
    if job_id in jobs_dict:
        job = jobs_dict[job_id]
        job.cancel_event.set()
        # Set status to "stopped" (not "cancelled")
        job.status = "stopped"
        job.log("Job stopped by user.")
        update_jobs_list()
        job.ui["cancel_button"].config(state=tk.DISABLED)
        job.ui["resume_button"].config(state=tk.NORMAL)
        save_job_state(job)

def resume_job(job_id):
    job = jobs_dict.get(job_id)
    if not job:
        return
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
            job.log("Job finished processing after resume.")
            original_cases = consolidation.load_original_cases(job.input_file)
            job.log(f"Loaded {len(original_cases)} original cases.")
            error_log = consolidation.load_error_log(job.api_error_log_file)
            job.log(f"Loaded {len(error_log)} error entries.")
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
            job.log("Consolidation phase complete.")
            job.ui["save_button"].config(state=tk.NORMAL)
        save_job_state(job)
        update_jobs_list()
    threading.Thread(target=run_resumed_job, daemon=True).start()

def save_job_results(job):
    dest_file = filedialog.asksaveasfilename(
        title="Save Consolidated Excel File As",
        defaultextension=".xlsx",
        filetypes=[("Excel Files", "*.xlsx")],
        initialfile=os.path.basename(job.consolidated_excel)
    )
    if dest_file:
        try:
            shutil.copy(job.consolidated_excel, dest_file)
            messagebox.showinfo("Success", f"Excel file saved successfully for Job {job.job_id[:8]}.")
            job.status = "finished"
            job.log("Job output saved. Clearing job from UI.")
            update_jobs_list()
            notebook.forget(job.ui["tab"])
            clear_job_state(job.job_id)
            del jobs_dict[job.job_id]
            update_jobs_list()
        except Exception as e:
            messagebox.showerror("Error", f"Failed to save file for Job {job.job_id[:8]}: {e}")

def start_new_job(main_window):
    #print("JOBS_DICT KEYS:", list(jobs_dict.keys()))
    for job in jobs_dict.values():
        print(f"→ Job {job.job_id[:8]} | logs length={len(job.logs)} | progress={job.progress_done}/{job.progress_total}")

    file_selected = prompt_for_input_file(main_window)
    if not file_selected:
        messagebox.showerror("Error", "No input file selected. Job cancelled.", parent=main_window)
        return
    selected_experiment = prompt_for_experiment_selection(main_window)
    if selected_experiment is None:
        messagebox.showinfo("Cancelled", "Experiment selection cancelled. Job not started.", parent=main_window)
        return
    config.experimentId = selected_experiment
    experiment_id = config.experimentId
    file_md5 = get_input_file_md5(file_selected)
    duplicate = None

    job = Job(file_selected, experiment_id)
    job.processed_tracking_file = unique_job_filename(job.input_file, job.experiment_id, "processed", "txt", job.job_id)
    job.api_401_tracking_file = unique_job_filename(job.input_file, job.experiment_id, "401", "txt", job.job_id)
    job.raw_output_file = unique_job_filename(job.input_file, job.experiment_id, "APIResponseRaw", "csv", job.job_id)
    job.api_response_file = unique_job_filename(job.input_file, job.experiment_id, "APIResponse", "csv", job.job_id)
    job.api_error_log_file = unique_job_filename(job.input_file, job.experiment_id, "APIError", "log", job.job_id)
    job.script_error_log_file = unique_job_filename(job.input_file, job.experiment_id, "ScriptError", "log", job.job_id)
    job.consolidated_csv = unique_job_filename(job.input_file, job.experiment_id, "Consolidated_Output", "csv", job.job_id)
    job.consolidated_excel = unique_job_filename(job.input_file, job.experiment_id, "Consolidated_Output", "xlsx", job.job_id)
    jobs_dict[job.job_id] = job
    update_jobs_list()
    create_job_tab(job)
    #print("🔸 After start_new_job(), jobs_dict keys:", list(jobs_dict.keys()))

    
    def run_job():
        processing.processing_main_job(job)
        if not job.cancel_event.is_set():
            job.status = "finished"
            job.log("Job finished processing.")
            original_cases = consolidation.load_original_cases(job.input_file)
            job.log(f"Loaded {len(original_cases)} original cases.")
            error_log = consolidation.load_error_log(job.api_error_log_file)
            job.log(f"Loaded {len(error_log)} error entries.")
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
            job.log("Consolidation phase complete.")
            job.ui["save_button"].config(state=tk.NORMAL)
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
    dialog.focus_force()
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
        return None  # No experiments available

    experiment_var = tk.StringVar()

    # Adjust combobox width to fit the longest experiment name
    max_length = max(len(s) for s in experiments.keys())
    combobox = ttk.Combobox(content_frame, textvariable=experiment_var,
                              values=list(experiments.keys()), state="readonly",
                              width=max_length + 2)
    combobox.pack(pady=10)

    # Pre-select current experiment if available
    default_name = None
    for name, exp_id in experiments.items():
        if exp_id == config.experimentId:
            default_name = name
            break
    if default_name:
        combobox.set(default_name)
    else:
        combobox.current(0)

    # Frame for buttons, placed horizontally
    button_frame = tk.Frame(content_frame)
    button_frame.pack(pady=10)

    # Dictionary to store the result
    result = {"experiment": None}

    def on_ok():
        selected = experiment_var.get()
        if selected in experiments:
            result["experiment"] = experiments[selected]
        dialog.destroy()

    def on_cancel():
        result["experiment"] = None
        dialog.destroy()

    ok_button = ttk.Button(button_frame, text="OK", command=on_ok)
    ok_button.pack(side=tk.LEFT, padx=10)

    cancel_button = ttk.Button(button_frame, text="Cancel", command=on_cancel)
    cancel_button.pack(side=tk.LEFT, padx=10)

    # Center the dialog
    dialog.update_idletasks()
    screen_width = dialog.winfo_screenwidth()
    screen_height = dialog.winfo_screenheight()
    x = (screen_width // 2) - (fixed_width // 2)
    y = (screen_height // 2) - (fixed_height // 2)
    dialog.geometry(f"{fixed_width}x{fixed_height}+{x}+{y}")

    dialog.wait_window()
    return result["experiment"]


def tk_ui_main():
    global job_list_tree, notebook
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
    quit_button = ttk.Button(control_frame, text="Quit", command=root.destroy)
    quit_button.pack(pady=2, fill=tk.X)
    notebook_frame = tk.Frame(main_frame)
    notebook_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
    notebook = ttk.Notebook(notebook_frame)
    notebook.pack(fill=tk.BOTH, expand=True)
    update_jobs_list()
    def update_ui():
        for job in jobs_dict.values():
            ui = job.ui
            ui["progress_var"].set(job.progress_done)
            ui["progress_bar"].config(maximum=job.progress_total or 1)
            if not ui.get("last_log_index"):
                ui["last_log_index"] = 0
            new_entries = job.logs[ui["last_log_index"]:]
            for entry in new_entries:
                ui["log_text"].insert(tk.END, entry+"\n")
            ui["last_log_index"] = len(job.logs)
        root.after(500, update_ui)
    update_ui()
    root.mainloop()

if __name__ == "__main__":
    tk_ui_main()
