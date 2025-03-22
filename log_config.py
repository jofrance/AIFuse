import logging
import os
from config import OUTPUT_DIR  # Make sure OUTPUT_DIR is defined in config.py

# Ensure the output directory exists.
if not os.path.exists(OUTPUT_DIR):
    os.makedirs(OUTPUT_DIR)

# Define the log file path.
LOG_FILE = os.path.join(OUTPUT_DIR, "app.log")

# Configure the logging.
logging.basicConfig(
    level=logging.INFO,  # Set default logging level (adjust as needed)
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, mode="a", encoding="latin-1"),
        logging.StreamHandler()  # Optional: also output to console
    ]
)

# Create the logger.
logger = logging.getLogger(__name__)
