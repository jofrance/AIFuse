import configparser
import os
import threading
import hashlib

def load_configuration(config_file='config.ini'):
    """Load configuration settings from an INI file."""
    parser = configparser.ConfigParser()
    parser.optionxform = str  # Preserve key case
    parser.read(config_file)
    return parser

# Load the configuration from config.ini.
CONFIG = load_configuration()

# --- Paths Section ---
# Read the output directory from the INI file, default to "Results".
OUTPUT_DIR = CONFIG.get('Paths', 'OUTPUT_DIR', fallback='Results')
if not os.path.exists(OUTPUT_DIR):
    os.makedirs(OUTPUT_DIR)

# Build file paths using the output directory and values from the INI file.
default_consolidated_csv = os.path.join(
    OUTPUT_DIR, CONFIG.get('Paths', 'default_consolidated_csv', fallback="Consolidated_Output.csv")
)
default_consolidated_excel = os.path.join(
    OUTPUT_DIR, CONFIG.get('Paths', 'default_consolidated_excel', fallback="Consolidated_Output.xlsx")
)
RAW_OUTPUT_FILE = os.path.join(
    OUTPUT_DIR, CONFIG.get('Paths', 'RAW_OUTPUT_FILE', fallback="50CasesLinuxAPIResponseRaw.csv")
)
API_RESPONSE_FILE = os.path.join(
    OUTPUT_DIR, CONFIG.get('Paths', 'API_RESPONSE_FILE', fallback="50CasesLinuxAPIResponse.csv")
)
API_ERROR_LOG_FILE = os.path.join(
    OUTPUT_DIR, CONFIG.get('Paths', 'API_ERROR_LOG_FILE', fallback="50CasesLinuxAPIError.log")
)
SCRIPT_ERROR_LOG_FILE = os.path.join(
    OUTPUT_DIR, CONFIG.get('Paths', 'SCRIPT_ERROR_LOG_FILE', fallback="50CasesLinuxScriptError.log")
)
PROCESSED_TRACKING_FILE = os.path.join(
    OUTPUT_DIR, CONFIG.get('Paths', 'PROCESSED_TRACKING_FILE', fallback="CasesLinuxProcessed.txt")
)
API_401_ERROR_TRACKING_FILE = os.path.join(
    OUTPUT_DIR, CONFIG.get('Paths', 'API_401_ERROR_TRACKING_FILE', fallback="50CasesLinuxAPI401Errors.txt")
)

# --- API and MSAL Configuration ---
apiUrl = CONFIG.get('API', 'apiUrl', fallback='https://zebra-ai-api-prd.azurewebsites.net/')
experimentId = CONFIG.get('API', 'experimentId', fallback='582c5e80-b307-43f9-bc86-efd0a6551907')
API_TIMEOUT = CONFIG.getint('API', 'API_TIMEOUT', fallback=30)
##### For Managed Identity #####
#APP_CLIENT_ID = CONFIG.get('API', 'APP_CLIENT_ID', fallback='https://zebra-ai-api-prd.azurewebsites.net/')
#RESOURCE_TENANT_ID = CONFIG.get('API', 'RESOURCE_TENANT_ID', fallback='https://zebra-ai-api-prd.azurewebsites.net/')
#AZURE_REGION = CONFIG.get('API', 'AZURE_REGION', fallback='https://zebra-ai-api-prd.azurewebsites.net/')
#MI_CLIENT_ID = CONFIG.get('API', 'MI_CLIENT_ID', fallback='https://zebra-ai-api-prd.azurewebsites.net/')
#AUDIENCE = CONFIG.get('API', 'AUDIENCE', fallback='https://zebra-ai-api-prd.azurewebsites.net/')
##### For Managed Identity #####

# --- Authentication Settings ---
client_id = CONFIG.get('Authentication', 'client_id', fallback='751c47e2-782e-4d75-b304-37f68a9d45fd')
authority = CONFIG.get('Authentication', 'authority', fallback='https://login.microsoftonline.com/72f988bf-86f1-41af-91ab-2d7cd011db47')
scopes = CONFIG.get('Authentication', 'scopes', fallback='api://9021b3a5-1f0d-4fb7-ad3f-d6989f0432d8/.default').split(',')

# --- Shared Globals for Authentication (used by auth.py) ---
access_token = None
token_lock = threading.Lock()
api_header = None
msal_app = None

# --- Global State for Processing (used by processing.py) ---
total_cases = 0
cases_processed = 0
progress_lock = threading.Lock()
processing_details = []
details_lock = threading.Lock()

# --- Flags for Resume and Retry Options (used by processing.py) ---
resume_mode = False
retry_401_flag = False

# --- ARGS will be set in main.py after command-line parsing ---
ARGS = None

def generate_filename(source_file_path, experiment_id, basename, extension):
    """
    Generate a consistent filename using the MD5 hash of the source file content,
    the experiment ID, and a human-readable basename.
    The final filename will be: <md5>_<experiment_id>_<basename>.<extension>
    and will be placed in the OUTPUT_DIR.
    """
    try:
        with open(source_file_path, 'rb') as f:
            content = f.read()
        md5sum = hashlib.md5(content).hexdigest()
    except Exception as e:
        raise RuntimeError(f"Error reading file {source_file_path}: {e}") from e
    filename = f"{md5sum}_{experiment_id}_{basename}.{extension}"
    return os.path.join(OUTPUT_DIR, filename)

# --- Parsing Methods Configuration ---
PARSING_CONFIG_FILE = "parsing_explanations.ini"
PARSING_CONFIG = configparser.ConfigParser()
PARSING_CONFIG.optionxform = str  # Preserve key case
if os.path.exists(PARSING_CONFIG_FILE):
    PARSING_CONFIG.read(PARSING_CONFIG_FILE)
    # Validate that both sections have at least one value.
    if not PARSING_CONFIG.has_section("Parsing") or not list(PARSING_CONFIG.items("Parsing")):
        raise ValueError(f"'{PARSING_CONFIG_FILE}' must contain at least one value in the [Parsing] section.")
    if not PARSING_CONFIG.has_section("ParsingExplanations") or not list(PARSING_CONFIG.items("ParsingExplanations")):
        raise ValueError(f"'{PARSING_CONFIG_FILE}' must contain at least one value in the [ParsingExplanations] section.")
else:
    # Fallback defaults if the file does not exist.
    PARSING_CONFIG.read_dict({
        "Parsing": {
            "TXT": "TXT",
            "JSON": "JSON"
        },
        "ParsingExplanations": {
            "TXT": "Parses plain text output from the API.",
            "JSON": "Returns the complete JSON response from the API."
        }
    })

