import threading
import uuid
import json
import os
import hashlib
import config
import time

class Job:
    def __init__(self, input_file, experiment_id):
        self.job_id = str(uuid.uuid4())
        self.input_file = input_file
        self.experiment_id = experiment_id
        self.cancel_event = threading.Event()
        self.status = "running"  # possible values: running, paused, finished, cancelled
        self.progress_total = 0
        self.progress_done = 0
        self.logs = []
        self.result_file = None  # path to output result if finished
        # File paths for job-specific outputs:
        self.processed_tracking_file = ""
        self.api_401_tracking_file = ""
        self.raw_output_file = ""
        self.api_response_file = ""
        self.api_error_log_file = ""
        self.script_error_log_file = ""
        self.consolidated_csv = ""
        self.consolidated_excel = ""
        self.consolidated_txt = ""

        # per-job state attributes:
        self.api_header = None
        self.total_cases = 0
        self.cases_processed = 0
        self.processing_details = []
        self.resume_mode = False       # Indicates if the job should resume from saved progress
        self.retry_401_flag = False    # For handling repeated 401 errors
        
        # NEW: Consolidation lock for TXT mode
        self.consolidation_lock = threading.Lock()
        
        # Placeholder for UI components in the Tkinter tab
        self.ui = {}

        # New attributes for resumption
        self.parsing_method = "CSV"    # Default to CSV if not set externally
        self.start_time = time.time()  # When the job started

    def log(self, message):
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        log_entry = f"[{timestamp}] {message}"
        self.logs.append(log_entry)

    def to_dict(self):
        # Convert the job state to a dictionary for persistence.
        return {
            "job_id": self.job_id,
            "input_file": self.input_file,
            "experiment_id": self.experiment_id,
            "status": self.status,
            "progress_total": self.progress_total,
            "progress_done": self.progress_done,
            "logs": self.logs,
            "result_file": self.result_file,
            # File paths
            "processed_tracking_file": self.processed_tracking_file,
            "api_401_tracking_file": self.api_401_tracking_file,
            "raw_output_file": self.raw_output_file,
            "api_response_file": self.api_response_file,
            "api_error_log_file": self.api_error_log_file,
            "script_error_log_file": self.script_error_log_file,
            "consolidated_csv": self.consolidated_csv,
            "consolidated_excel": self.consolidated_excel,
            "consolidated_txt": self.consolidated_txt,
            # Additional state for resumption
            "parsing_method": self.parsing_method,
            "start_time": self.start_time,
            "resume_mode": self.resume_mode,
            "retry_401_flag": self.retry_401_flag
        }

    @classmethod
    def from_dict(cls, data):
        job = cls(data["input_file"], data["experiment_id"])
        job.job_id = data["job_id"]
        job.status = data["status"]
        job.progress_total = data["progress_total"]
        job.progress_done = data["progress_done"]
        job.logs = data["logs"]
        job.result_file = data.get("result_file")
        job.processed_tracking_file = data.get("processed_tracking_file", "")
        job.api_401_tracking_file = data.get("api_401_tracking_file", "")
        job.raw_output_file = data.get("raw_output_file", "")
        job.api_response_file = data.get("api_response_file", "")
        job.api_error_log_file = data.get("api_error_log_file", "")
        job.script_error_log_file = data.get("script_error_log_file", "")
        job.consolidated_csv = data.get("consolidated_csv", "")
        job.consolidated_excel = data.get("consolidated_excel", "")
        job.consolidated_txt = data.get("consolidated_txt", "")
        # Reinitialize threading event (do not persist the event object)
        job.cancel_event = threading.Event()
        # Restore additional state; if not found, assign default values.
        job.parsing_method = data.get("parsing_method", "CSV")
        job.start_time = data.get("start_time", time.time())
        job.resume_mode = data.get("resume_mode", False)
        job.retry_401_flag = data.get("retry_401_flag", False)
        return job

def get_input_file_md5(input_file):
    try:
        with open(input_file, "rb") as f:
            content = f.read()
        md5sum = hashlib.md5(content).hexdigest()
        return md5sum
    except Exception:
        return None

# Persistence functions
JOBS_STATE_DIR = os.path.join(config.OUTPUT_DIR, "jobs_state")
if not os.path.exists(JOBS_STATE_DIR):
    os.makedirs(JOBS_STATE_DIR)

def save_job_state(job: Job):
    file_path = os.path.join(JOBS_STATE_DIR, f"{job.job_id}.json")
    with open(file_path, "w", encoding="latin-1") as f:
        json.dump(job.to_dict(), f, indent=4)

def load_all_jobs():
    jobs = {}
    for filename in os.listdir(JOBS_STATE_DIR):
        if filename.endswith(".json"):
            with open(os.path.join(JOBS_STATE_DIR, filename), "r", encoding="latin-1") as f:
                data = json.load(f)
                job = Job.from_dict(data)
                jobs[job.job_id] = job
    return jobs

def clear_job_state(job_id):
    file_path = os.path.join(JOBS_STATE_DIR, f"{job_id}.json")
    if os.path.exists(file_path):
        os.remove(file_path)
