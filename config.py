import os
import threading

# Ensure output directory exists
OUTPUT_DIR = "Results"
if not os.path.exists(OUTPUT_DIR):
    os.makedirs(OUTPUT_DIR)

# Intermediate and final file names
default_consolidated_csv = os.path.join(OUTPUT_DIR, "")#Consolidated_Output.csv
default_consolidated_excel = os.path.join(OUTPUT_DIR, "")#Consolidated_Output.xlsx
RAW_OUTPUT_FILE = os.path.join(OUTPUT_DIR, "")#APIResponseRaw.csv
API_RESPONSE_FILE = os.path.join(OUTPUT_DIR, "")#APIResponse.csv
API_ERROR_LOG_FILE = os.path.join(OUTPUT_DIR, "")#APIResponse.csv
SCRIPT_ERROR_LOG_FILE = os.path.join(OUTPUT_DIR, "")#ScriptError.log
PROCESSED_TRACKING_FILE = os.path.join(OUTPUT_DIR, "")#CasesProcessed.txt
API_401_ERROR_TRACKING_FILE = os.path.join(OUTPUT_DIR, "")#API401Errors.txt

# API and MSAL configuration
apiUrl = ''#'Your api URL goes here'
experimentId = '' #'123-456-789'
API_TIMEOUT = 30  # seconds

# Shared globals for authentication (used by auth.py)
access_token = None
token_lock = threading.Lock()
api_header = None
msal_app = None

# Global state for processing (used by processing.py)
total_cases = 0
cases_processed = 0
progress_lock = threading.Lock()
processing_details = []
details_lock = threading.Lock()

# Flags for resume and retry options (used by processing.py)
resume_mode = False
retry_401_flag = False

# ARGS will be set in main.py after parsing command-line arguments
ARGS = None

# Settings for Authentication
client_id=''#Your APP CLient ID goes Here
authority=''#https://login.microsoftonline.com/ goes here
scopes = ['']#Your API scope goes here

