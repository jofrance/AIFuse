import time
import threading
from msal import PublicClientApplication
import config
from log_config import logger

scopes = config.scopes

def get_access_token(parent_window_handle=None):
    """Acquire an access token using MSAL.
    
    If a parent_window_handle is provided (for GUI apps), it will be used.
    Otherwise, if running in console mode, PublicClientApplication.CONSOLE_WINDOW_HANDLE is used.
    """
    # Import PublicClientApplication handle for console apps.
    from msal import PublicClientApplication
    if parent_window_handle is None:
        parent_window_handle = PublicClientApplication.CONSOLE_WINDOW_HANDLE
    # Initialize msal_app in config if needed.
    if config.msal_app is None:
        config.msal_app = PublicClientApplication(
            client_id = config.client_id,
            authority = config.authority,
            enable_broker_on_windows=True
        )
    accounts = config.msal_app.get_accounts()
    # Ensure scopes is a list.
    s = scopes
    if isinstance(s, str):
        s = [s]
    result = None
    if accounts:
        result = config.msal_app.acquire_token_silent(s, account=accounts[0])
        if result and "access_token" in result:
            return result["access_token"]
    result = config.msal_app.acquire_token_interactive(s, parent_window_handle=parent_window_handle)
    if "access_token" in result:
        logger.info("Got access token.")
        return result["access_token"]
    else:
        logger.info("Failed to get access token.")
        raise Exception('Failed to get access token')

def refresh_token(stop_event):
    """Background thread to refresh token every hour."""
    while not stop_event.is_set():
        try:
            new_token = get_access_token()  # In console mode; pass window handle for GUI apps.
            with config.token_lock:
                config.access_token = new_token
            print("Access token refreshed.")
            logger.info("Access Token refreshed.")
        except Exception as e:
            print(f"Error refreshing access token: {e}")
            logger.info("Error refreshing access token.")
        stop_event.wait(3600)

if __name__ == "__main__":
    # For testing purposes, call get_access_token() in console mode.
    token = get_access_token()
    print("Token:", token)
