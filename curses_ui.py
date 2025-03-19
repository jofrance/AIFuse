import curses
import time
import itertools
import threading
from log_config import logger
import processing
import config
import utils
from config import generate_filename

def curses_main(stdscr):
    curses.curs_set(0)
    # Temporarily disable non-blocking mode for resume prompt:
    stdscr.nodelay(False)
    config.PROCESSED_TRACKING_FILE = generate_filename(config.ARGS.file, config.experimentId, "processed", "txt")
    config.API_401_ERROR_TRACKING_FILE = generate_filename(config.ARGS.file, config.experimentId, "401", "txt")
    # After the prompt, re-enable non-blocking mode for the spinner/UI loop:
    stdscr.nodelay(True)
    spinner_cycle = itertools.cycle(["|", "/", "-", "\\"])
    start_time = time.time()
    
    # Prompt for resume/start fresh options using the existing function.
    processing.check_resume_option(stdscr)

    # Start processing in a background thread.
    processing_thread = threading.Thread(target=processing.processing_main)
    processing_thread.start()

    # Update the curses UI until processing is complete.
    while processing_thread.is_alive() or config.cases_processed < config.total_cases:
        elapsed_time = time.time() - start_time
        minutes, seconds = divmod(int(elapsed_time), 60)
        stdscr.move(0, 0)
        stdscr.clrtoeol()
        stdscr.addstr(0, 0, f"Processing cases: {config.cases_processed}/{config.total_cases}")
        stdscr.move(1, 0)
        stdscr.clrtoeol()
        stdscr.addstr(1, 0, f"{next(spinner_cycle)}")
        stdscr.move(2, 0)
        stdscr.clrtoeol()
        stdscr.addstr(2, 0, f"Elapsed time: {minutes:02}:{seconds:02}")
        with config.details_lock:
            details_to_show = config.processing_details[-20:]
        for i, msg in enumerate(details_to_show):
            stdscr.move(4 + i, 0)
            stdscr.clrtoeol()
            stdscr.addstr(4 + i, 0, msg[:curses.COLS - 1])
        stdscr.refresh()
        time.sleep(0.1)
    
    stdscr.nodelay(False)
    max_y, _ = stdscr.getmaxyx()
    stdscr.move(max_y - 1, 0)
    stdscr.clrtoeol()
    stdscr.addstr(max_y - 1, 0, "Processing complete! Press Enter to exit.")
    logger.info("Processing completed.")
    stdscr.refresh()
    
    while True:
        key = stdscr.getch()
        if key in (10, 13):
            break
    processing_thread.join()
