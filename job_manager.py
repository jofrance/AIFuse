import threading
import uuid
import json
import os
import hashlib
import config
import time

class Job:
    def __init__(self, job_id=None, input_file=None, experiment_id=None, experiment_name=None, parsing_method=None, threads=0, batch_size=0):
        self.job_id = job_id or str(uuid.uuid4())
        self.input_file = input_file
        self.experiment_id = experiment_id
        self.experiment_name = experiment_name
        self.parsing_method = parsing_method
        self.threads = threads  # Add thread count parameter
        self.batch_size = batch_size  # Add batch size parameter
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
        self.start_time = time.time()  # When the job started
        
        # Add file locks for thread safety
        self.tracking_file_lock = threading.Lock()        # For processed_tracking_file
        self.error_file_lock = threading.Lock()           # For api_error_log_file
        self.api_response_lock = threading.Lock()         # For api_response_file
        self.raw_output_lock = threading.Lock()           # For raw_output_file
        self.script_error_lock = threading.Lock()         # For script_error_log_file
        self.api_401_lock = threading.Lock()              # For api_401_tracking_file
        self.logs_lock = threading.Lock()  # Add this new lock for logs
        self.progress_lock = threading.Lock()  # Add this new lock


    def log(self, message):
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        log_entry = f"[{timestamp}] {message}"
        self.logs.append(log_entry)

    def to_dict(self):
        return {
            'job_id': self.job_id,
            'input_file': self.input_file,
            'experiment_id': self.experiment_id,
            'experiment_name': self.experiment_name,
            'parsing_method': self.parsing_method,
            'threads': self.threads,
            'batch_size': self.batch_size,
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
            "start_time": self.start_time,
            "resume_mode": self.resume_mode,
            "retry_401_flag": self.retry_401_flag
        }

    @classmethod
    def from_dict(cls, data):
        job = cls(
            job_id=data.get('job_id'),
            input_file=data.get('input_file'),
            experiment_id=data.get('experiment_id'),
            experiment_name=data.get('experiment_name'),
            parsing_method=data.get('parsing_method'),
            threads=data.get('threads', 0),  # Default to 0 if not present (backward compatibility)
            batch_size=data.get('batch_size', 0)  # Default to 0 if not present
        )
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

def load_job(job_id):
    file_path = os.path.join(JOBS_STATE_DIR, f"{job_id}.json")
    if os.path.exists(file_path):
        with open(file_path, "r", encoding="latin-1") as f:
            data = json.load(f)
            job = Job.from_dict(data)
            # Ensure threads and batch_size have defaults if not present
            if not hasattr(job, 'threads'):
                job.threads = 0
            if not hasattr(job, 'batch_size'):
                job.batch_size = 0
            return job
    return None
